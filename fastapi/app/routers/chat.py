import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

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

            # Detect group vs 1-1
            iv = msg.get("iv")
            is_encrypted = msg.get("is_encrypted", False)
            media_id = msg.get("media_id")
            media_mime_type = msg.get("media_mime_type")
            media_size = msg.get("media_size")
            media_duration = msg.get("media_duration")
            reply_to = msg.get("reply_to")
            conversation_id = msg.get("conversation_id")
            key_version = msg.get("key_version")

            if conversation_id:
                # Group message
                try:
                    result = await service.send_group_message(
                        conversation_id=conversation_id,
                        sender_id=msg["from"],
                        content=msg.get("content", "") or "",
                        client_message_id=msg.get("client_message_id"),
                        iv=iv,
                        is_encrypted=is_encrypted,
                        media_id=media_id,
                        media_mime_type=media_mime_type,
                        media_size=media_size,
                        media_duration=media_duration,
                        reply_to=reply_to,
                        key_version=key_version,
                    )
                except Exception as e:
                    await websocket.send_text(f"Error: {str(e)}")
                    continue
                ack = result.get("ack", {})
                participants = result.get("participants", [])
                if media_id:
                    ack["media_id"] = media_id
                    if media_mime_type:
                        ack["media_mime_type"] = media_mime_type
                    if media_size is not None:
                        ack["media_size"] = media_size
                    if media_duration is not None:
                        ack["media_duration"] = media_duration
                await websocket.send_text(json.dumps({"ack": ack}))
                payload = json.dumps({
                    "type": "message",
                    "from": msg["from"],
                    "content": msg.get("content", "") or "",
                    "ack": ack,
                    "iv": iv,
                    "is_encrypted": is_encrypted,
                    "media_id": media_id,
                    "media_mime_type": media_mime_type,
                    "media_size": media_size,
                    "media_duration": media_duration,
                    "reply_to": reply_to,
                    "conversation_id": conversation_id,
                    "key_version": key_version,
                })
                targets = [p for p in participants if p != msg["from"]]
                for target in targets:
                    try:
                        if getattr(bus, "enabled", False):
                            await (await get_bus()).publish(f"user:{target}", payload)
                        else:
                            await manager.send_personal_message(target, payload)
                    except Exception:
                        pass
                
                # Send FCM notification to offline group members
                convo = await service._conversation_repo.get_by_id(conversation_id)
                group_name = convo.get("name", "Group") if convo else "Group"
                message_preview = msg.get("content", "") or "[Media]"
                is_encrypted = msg.get("is_encrypted", False)
                for target in targets:
                    asyncio.create_task(
                        service.send_fcm_notification_for_message(
                            db=db,
                            receiver_id=target,
                            sender_id=msg["from"],
                            message_content=message_preview,
                            conversation_id=conversation_id,
                            is_group=True,
                            group_name=group_name,
                            is_encrypted=is_encrypted
                        )
                    )
                continue

            # 1-1 message
            if not all(k in msg for k in ("from", "to", "content")):
                await websocket.send_text("Invalid message payload")
                continue
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
                media_duration=media_duration,
                reply_to=reply_to,
            ) 
            if media_id:
                ack["ack"]["media_id"] = media_id
                if media_mime_type:
                    ack["ack"]["media_mime_type"] = media_mime_type
                if media_size is not None:
                    ack["ack"]["media_size"] = media_size
                if media_duration is not None:
                    ack["ack"]["media_duration"] = media_duration
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
                "media_duration": media_duration,
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
            # push notification if offline (old system - kept for backward compatibility)
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
            
            # Send FCM notification (new system)
            message_preview = msg.get("content", "") or "[Media]"
            is_encrypted = msg.get("is_encrypted", False)
            asyncio.create_task(
                service.send_fcm_notification_for_message(
                    db=db,
                    receiver_id=msg["to"],
                    sender_id=msg["from"],
                    message_content=message_preview,
                    conversation_id=ack["ack"]["conversation_id"],
                    is_group=False,
                    is_encrypted=is_encrypted
                )
            )
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


class ReactRequest(BaseModel):
    emoji: str


@router.post("/{message_id}/react")
async def react_to_message(
    message_id: str,
    body: ReactRequest,
    current_user: dict = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
    db = Depends(mongo_db_dependency)
):
    """
    Add or toggle a reaction to a message.
    If user already reacted with same emoji, remove it.
    If user reacted with different emoji, replace it.
    """
    from bson import ObjectId
    from app.repositories.message_repository import MessageRepository
    
    msg_repo = MessageRepository(db)
    
    try:
        # Add/update reaction
        updated_message = await msg_repo.add_reaction(message_id, current_user["_id"], body.emoji)
        
        if not updated_message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        
        # Get conversation participants to broadcast
        conversation_id = str(updated_message.get("conversation_id", ""))
        sender_id = updated_message.get("sender_id")
        receiver_id = updated_message.get("receiver_id")
        
        # Broadcast reaction via WebSocket
        reactions = updated_message.get("reactions", {}) or {}
        payload = json.dumps({
            "type": "reaction",
            "message_id": message_id,
            "conversation_id": conversation_id,
            "user_id": current_user["_id"],
            "emoji": body.emoji,
            "reactions": reactions  # Send full reactions map
        })
        
        bus = await get_bus()
        # Send to both participants
        for user_id in [sender_id, receiver_id]:
            if user_id and user_id != current_user["_id"]:
                if getattr(bus, "enabled", False):
                    await bus.publish(f"user:{user_id}", payload)
                else:
                    await manager.send_personal_message(user_id, payload)
        
        return {
            "message_id": message_id,
            "reactions": reactions
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add reaction: {str(e)}"
        )


