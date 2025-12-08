import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

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
    heartbeat_task = None
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
                    ack_payload = {
                        "message_id": m["_id"],
                        "conversation_id": str(m["conversation_id"]),
                    }
                    if m.get("client_message_id"):
                        ack_payload["client_message_id"] = m.get("client_message_id")
                    await websocket.send_text(json.dumps({
                        "type": "message",
                        "from": m["sender_id"],
                        "content": m["content"],
                        "ack": ack_payload,
                        "iv": m.get("iv"),
                        "is_encrypted": m.get("is_encrypted", False),
                        "media_id": m.get("media_id"),
                        "media_mime_type": m.get("media_mime_type"),
                        "media_size": m.get("media_size"),
                        "reply_to": m.get("reply_to"),
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
            # Support E2EE & media: extract extra fields if present
            iv = msg.get("iv")
            is_encrypted = msg.get("is_encrypted", False)
            media_id = msg.get("media_id")
            media_mime_type = msg.get("media_mime_type")
            media_size = msg.get("media_size")
            reply_to = msg.get("reply_to")
            ack = await service.send_message(
                msg["from"], 
                msg["to"], 
                msg["content"], 
                msg.get("client_message_id"),
                iv=iv,
                is_encrypted=is_encrypted,
                media_id=media_id,
                media_mime_type=media_mime_type,
                media_size=media_size,
                reply_to=reply_to,
            ) 
            if media_id:
                ack["ack"]["media_id"] = media_id
                if media_mime_type:
                    ack["ack"]["media_mime_type"] = media_mime_type
                if media_size is not None:
                    ack["ack"]["media_size"] = media_size
            # gửi ack về cho sender
            await websocket.send_text(json.dumps(ack))
            # đẩy message realtime tới receiver
            payload = json.dumps({
                "type": "message",
                "from": msg["from"],
                "content": msg["content"],
                "ack": ack["ack"],
                "iv": iv,
                "is_encrypted": is_encrypted,
                "media_id": media_id,
                "media_mime_type": media_mime_type,
                "media_size": media_size,
                "reply_to": reply_to,
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
                        body=(msg["content"][:100] if msg.get("content") else "[Media]"),
                        data={"conversation_id": ack["ack"]["conversation_id"], "message_id": ack["ack"]["message_id"], "from": msg["from"]},
                    )
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
        
        # Check if user has no more active connections
        has_other_connections = user_id in manager.active_connections and len(manager.active_connections[user_id]) > 0
        
        if not has_other_connections:
            # User has no more connections, mark as offline
            try:
                from app.repositories.user_repository import UserRepository
                user_repo = UserRepository(db)
                await user_repo.update_last_seen(user_id)
            except Exception:
                pass  # Ignore errors when updating last_seen
            
            # Clear presence key in Redis immediately
            if getattr(bus, "enabled", False):
                try:
                    await bus.clear_presence(user_id)
                except Exception:
                    pass
        
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
        # Cancel heartbeat task if it exists
        if heartbeat_task:
            try:
                heartbeat_task.cancel()
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


@router.delete("/{message_id}")
async def delete_message(
    message_id: str,
    current_user: dict = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
    db = Depends(mongo_db_dependency)
):
    """
    Delete (recall) a message. Only the sender can delete their own message.
    Sends realtime notification to receiver.
    """
    from bson import ObjectId
    
    # Get message info before deleting (to get receiver_id and conversation_id)
    msg_repo = MessageRepository(db)
    message = await msg_repo.collection.find_one({"_id": ObjectId(message_id)})
    
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )
    
    # Only sender can delete their own message
    if message.get("sender_id") != current_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this message"
        )
    
    # Delete the message
    deleted = await service.delete_message(message_id, current_user["_id"])
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete message"
        )
    
    # Send realtime notification to receiver
    receiver_id = message.get("receiver_id")
    conversation_id = str(message.get("conversation_id", ""))
    
    if receiver_id:
        payload = json.dumps({
            "type": "message_deleted",
            "message_id": message_id,
            "conversation_id": conversation_id,
            "from": current_user["_id"]
        })
        
        bus = await get_bus()
        if getattr(bus, "enabled", False):
            await bus.publish(f"user:{receiver_id}", payload)
        else:
            await manager.send_personal_message(receiver_id, payload)
    
    return {"msg": "Message deleted successfully"}


@router.post("/mark_read")
async def mark_read(body: Dict[str, Any] | None = None, current_user: dict = Depends(get_current_user), service: ChatService = Depends(get_chat_service), db = Depends(mongo_db_dependency)):
    from_user_id = None
    if body and isinstance(body, dict):
        from_user_id = body.get("from_user_id")
        conversation_id = body.get("conversation_id")
    else:
        conversation_id = None
    
    # Mark messages as read
    count = await service.mark_read(current_user["_id"], from_user_id, conversation_id)
    
    # If messages were marked as read, send "seen" events via WebSocket to senders
    if count > 0:
        bus = await get_bus()
        msg_repo = MessageRepository(db)
        
        if conversation_id:
            # For conversation-specific mark_read, find the sender (other participant)
            try:
                from bson import ObjectId
                from app.repositories.conversation_repository import ConversationRepository
                convo_repo = ConversationRepository(db)
                convo_oid = ObjectId(conversation_id)
                conversation = await convo_repo.collection.find_one({"_id": convo_oid})
                
                if conversation:
                    participants = conversation.get("participants", [])
                    # Find the sender (the other participant, not the current user)
                    sender_id = None
                    for p in participants:
                        if p != current_user["_id"]:
                            sender_id = p
                            break
                    
                    if sender_id:
                        # Get the most recent unread message from this sender in this conversation
                        # to get a message_id for the seen event
                        query = {
                            "conversation_id": convo_oid,
                            "sender_id": sender_id,
                            "receiver_id": current_user["_id"],
                            "seen": True  # Now it's seen
                        }
                        recent_msg = await msg_repo.collection.find_one(query, sort=[("timestamp", -1)])
                        
                        if recent_msg:
                            payload = json.dumps({
                                "type": "seen",
                                "message_id": str(recent_msg["_id"]),
                                "conversation_id": conversation_id,
                                "from": current_user["_id"]
                            })
                            
                            if getattr(bus, "enabled", False):
                                await (await get_bus()).publish(f"user:{sender_id}", payload)
                            else:
                                await manager.send_personal_message(sender_id, payload)
            except Exception as e:
                # If error, just continue without sending seen event
                pass
        elif from_user_id:
            # For user-specific mark_read, send seen event to that user
            try:
                # Get the most recent message from this user
                query = {
                    "sender_id": from_user_id,
                    "receiver_id": current_user["_id"],
                    "seen": True
                }
                recent_msg = await msg_repo.collection.find_one(query, sort=[("timestamp", -1)])
                
                if recent_msg:
                    conv_id = str(recent_msg.get("conversation_id", ""))
                    payload = json.dumps({
                        "type": "seen",
                        "message_id": str(recent_msg["_id"]),
                        "conversation_id": conv_id,
                        "from": current_user["_id"]
                    })
                    
                    if getattr(bus, "enabled", False):
                        await (await get_bus()).publish(f"user:{from_user_id}", payload)
                    else:
                        await manager.send_personal_message(from_user_id, payload)
            except Exception:
                pass
    
    return {"updated": count}


