import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app.database.connection import mongo_db_dependency
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.services.chat_service import ChatService
from app.utils.dependencies import get_current_user
from app.utils.websocket_manager import ConnectionManager
from app.utils.security import decode_access_token
from app.utils.realtime_bus import get_bus
import asyncio


router = APIRouter(prefix="/messages", tags=["chat"])
manager = ConnectionManager()


def get_chat_service(db = Depends(mongo_db_dependency)) -> ChatService:
    msg_repo = MessageRepository(db)
    convo_repo = ConversationRepository(db)
    return ChatService(msg_repo, convo_repo)


@router.websocket("/ws/chat/{user_id}")
async def chat_socket(websocket: WebSocket, user_id: str, service: ChatService = Depends(get_chat_service), db = Depends(mongo_db_dependency)):
    # JWT bảo vệ WS: nhận token qua query ?token=...
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if sub != user_id:
            await websocket.close(code=4403)
            return
    except Exception:
        await websocket.close(code=4401)
        return

    await manager.connect(user_id, websocket)
    bus = await get_bus()
    # Start Redis subscription (if enabled) to fanout messages to this connection
    sub_task = None
    if getattr(bus, "enabled", False):
        subscriber = await bus.subscribe(f"user:{user_id}", lambda m: websocket.send_text(m))
        sub_task = asyncio.create_task(subscriber.run())
        # presence heartbeat
        async def _presence_heartbeat():
            while True:
                try:
                    await bus.set_presence(user_id, ttl_seconds=60)
                except Exception:
                    pass
                await asyncio.sleep(30)
        heartbeat_task = asyncio.create_task(_presence_heartbeat())
    # resume: optional query resume_since (ms)
    try:
        resume_since = websocket.query_params.get("resume_since")
        if resume_since:
            try:
                since_ms = int(resume_since)
                # fetch missed messages to this user since timestamp
                msgs = await service._message_repo.get_for_receiver_since(user_id, since_ms)  # type: ignore
                for m in msgs:
                    await websocket.send_text(json.dumps({
                        "type": "message",
                        "from": m["sender_id"],
                        "content": m["content"],
                        "ack": {"message_id": m["_id"], "conversation_id": str(m["conversation_id"])},
                    }))
            except Exception:
                pass
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            # Expect msg = {"from": str, "to": str, "content": str, "client_message_id"?: str, "type"?: "typing_start|typing_stop"}
            if msg.get("type") in ("typing_start", "typing_stop"):
                # Fanout typing event đến người nhận
                payload = json.dumps({"type": msg["type"], "from": msg.get("from")})
                if getattr(bus, "enabled", False):
                    await (await get_bus()).publish(f"user:{msg.get('to')}", payload)
                else:
                    await manager.send_personal_message(msg.get("to"), payload)
                continue

            if msg.get("type") == "delivered":
                # {type:"delivered", message_id, conversation_id, from, to}
                if msg.get("message_id"):
                    try:
                        ok = await service.mark_message_delivered(msg["message_id"])
                        if ok:
                            payload = json.dumps({"type": "delivered", "message_id": msg["message_id"], "conversation_id": msg.get("conversation_id"), "from": msg.get("from")})
                            target = msg.get("to")
                            if getattr(bus, "enabled", False):
                                await (await get_bus()).publish(f"user:{target}", payload)
                            else:
                                await manager.send_personal_message(target, payload)
                    except Exception:
                        pass
                continue

            if msg.get("type") == "seen":
                # {type:"seen", message_id, conversation_id, from, to}
                if msg.get("message_id"):
                    try:
                        ok = await service.mark_message_seen(msg["message_id"])
                        if ok:
                            payload = json.dumps({"type": "seen", "message_id": msg["message_id"], "conversation_id": msg.get("conversation_id"), "from": msg.get("from")})
                            target = msg.get("to")
                            if getattr(bus, "enabled", False):
                                await (await get_bus()).publish(f"user:{target}", payload)
                            else:
                                await manager.send_personal_message(target, payload)
                    except Exception:
                        pass
                continue

            if not all(k in msg for k in ("from", "to", "content")):
                await websocket.send_text("Invalid message payload")
                continue
            ack = await service.send_message(msg["from"], msg["to"], msg["content"], msg.get("client_message_id")) 
            # gửi ack về cho sender
            await websocket.send_text(json.dumps(ack))
            # đẩy message realtime tới receiver
            payload = json.dumps({
                "type": "message",
                "from": msg["from"],
                "content": msg["content"],
                "ack": ack["ack"],
            })
            if getattr(bus, "enabled", False):
                await (await get_bus()).publish(f"user:{msg['to']}", payload)
            else:
                await manager.send_personal_message(msg["to"], payload)
            # attempt to mark delivered for receiver in this conversation
            try:
                await service.mark_delivered_for_receiver(ack["ack"]["conversation_id"], msg["to"])
            except Exception:
                pass
            # push notification if offline
            try:
                if await service.should_push_offline(msg["to"]):
                    await service.push_new_message(
                        db,
                        receiver_id=msg["to"],
                        title="New message",
                        body=msg["content"][:100],
                        data={"conversation_id": ack["ack"]["conversation_id"], "message_id": ack["ack"]["message_id"], "from": msg["from"]},
                    )
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
        if sub_task:
            sub = await get_bus()
            try:
                await sub.subscribe("_", lambda m: None)  # dummy to access class
            except Exception:
                pass
            try:
                await subscriber.cancel()  # type: ignore
            except Exception:
                pass
            try:
                sub_task.cancel()
            except Exception:
                pass


@router.get("/{friend_id}")
async def get_history(friend_id: str, current_user: dict = Depends(get_current_user), service: ChatService = Depends(get_chat_service)):
    # Deprecated: nên dùng /conversations và /conversations/{id}/messages
    return {"messages": []}


@router.get("/unread")
async def get_unread(from_user_id: Optional[str] = None, current_user: dict = Depends(get_current_user), service: ChatService = Depends(get_chat_service)):
    messages = await service.get_unread(current_user["_id"], from_user_id)
    return {"messages": messages}


@router.post("/mark_read")
async def mark_read(body: Dict[str, Any] | None = None, current_user: dict = Depends(get_current_user), service: ChatService = Depends(get_chat_service)):
    from_user_id = None
    if body and isinstance(body, dict):
        from_user_id = body.get("from_user_id")
        conversation_id = body.get("conversation_id")
    else:
        conversation_id = None
    count = await service.mark_read(current_user["_id"], from_user_id, conversation_id)
    return {"updated": count}


