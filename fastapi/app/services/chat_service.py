from typing import Any, Dict, List, Optional
import logging

from bson import ObjectId
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.conversation_key_repository import ConversationKeyRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.fcm_token_repository import FCMTokenRepository
from app.repositories.user_repository import UserRepository
from app.utils.notifications import get_push
from app.utils.realtime_bus import get_bus
from app.services.fcm_service import fcm_service

logger = logging.getLogger(__name__)


class ChatService:

    def __init__(self, message_repo: MessageRepository, conversation_repo: ConversationRepository) -> None:
        self._message_repo = message_repo
        self._conversation_repo = conversation_repo

    async def send_message(
        self,
        sender_id: str,
        receiver_id: str,
        content: str,
        client_message_id: str | None = None,
        iv: str | None = None,
        is_encrypted: bool = False,
        media_id: str | None = None,
        media_mime_type: str | None = None,
        media_size: int | None = None,
        media_duration: float | None = None,
        reply_to: str | None = None,
    ) -> Dict[str, Any]:
        if (not content or not content.strip()) and not media_id:
            raise ValueError("Message content cannot be empty")
        convo = await self._conversation_repo.get_or_create_one_to_one(sender_id, receiver_id)
        convo_oid = ObjectId(convo["_id"]) if isinstance(convo["_id"], str) else convo["_id"]
        saved = await self._message_repo.save_message(
            conversation_id=convo_oid,
            sender_id=sender_id,
            receiver_id=receiver_id,
            content=content.strip(),
            client_message_id=client_message_id,
            iv=iv,
            is_encrypted=is_encrypted,
            media_id=media_id,
            media_mime_type=media_mime_type,
            media_size=media_size,
            media_duration=media_duration,
            reply_to=reply_to,
        )
        # For encrypted messages, show encrypted indicator in preview
        if media_id:
            preview = "[Media]"
        elif is_encrypted:
            preview = "[Encrypted Message]"
        else:
            preview = content.strip()[:200]
        await self._conversation_repo.update_on_new_message(convo_oid, preview, receiver_id, sender_id)
        return {"ack": {"message_id": saved["_id"], "conversation_id": str(convo_oid), "client_message_id": client_message_id}}

    async def send_group_message(
        self,
        conversation_id: str,
        sender_id: str,
        content: str,
        client_message_id: str | None = None,
        iv: str | None = None,
        is_encrypted: bool = False,
        media_id: str | None = None,
        media_mime_type: str | None = None,
        media_size: int | None = None,
        media_duration: float | None = None,
        reply_to: str | None = None,
        key_version: int | None = None,
    ) -> Dict[str, Any]:
        from bson import ObjectId
        convo = await self._conversation_repo.get_by_id(conversation_id)
        if not convo:
            raise ValueError("Conversation not found")
        try:
            convo_oid = ObjectId(conversation_id)
        except Exception:
            raise ValueError("Invalid conversation id")
        participants = convo.get("participants", [])
        if sender_id not in participants:
            raise ValueError("You are not a participant of this conversation")
        saved = await self._message_repo.save_message(
            conversation_id=convo_oid,
            sender_id=sender_id,
            receiver_id="GROUP",
            content=content.strip() if content else "",
            client_message_id=client_message_id,
            iv=iv,
            is_encrypted=is_encrypted,
            media_id=media_id,
            media_mime_type=media_mime_type,
            media_size=media_size,
            media_duration=media_duration,
            reply_to=reply_to,
        )
        preview = "[Media]" if media_id else ("[Encrypted Message]" if is_encrypted else content.strip()[:200])
        await self._conversation_repo.update_on_new_group_message(convo_oid, preview, sender_id, participants)
        ack = {
            "message_id": saved["_id"],
            "conversation_id": conversation_id,
            "client_message_id": client_message_id,
        }
        if key_version:
            ack["key_version"] = key_version
        return {"ack": ack, "participants": participants}

    async def get_history(self, conversation_id: str, limit: int = 50, cursor: str | None = None):
        from bson import ObjectId
        return await self._message_repo.get_messages_by_conversation(ObjectId(conversation_id), limit=limit, cursor=cursor)

    async def get_unread(self, user_id: str, from_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return await self._message_repo.get_unread(user_id, from_user_id)

    async def mark_read(self, receiver_id: str, from_user_id: Optional[str] = None, conversation_id: Optional[str] = None) -> int:
        from bson import ObjectId
        convo_oid = ObjectId(conversation_id) if conversation_id else None
        modified = await self._message_repo.mark_read(receiver_id, from_user_id, conversation_id=conversation_id)
        if conversation_id:
            await self._conversation_repo.reset_unread(convo_oid, receiver_id)
        return modified

    async def list_conversations(self, user_id: str, limit: int = 20, cursor: str | None = None):
        return await self._conversation_repo.list_for_user(user_id, limit=limit, cursor=cursor)

    async def mark_delivered_for_receiver(self, conversation_id: str, receiver_id: str) -> int:
        from bson import ObjectId
        return await self._message_repo.mark_delivered_for_receiver(ObjectId(conversation_id), receiver_id)

    async def mark_message_delivered(self, message_id: str) -> bool:
        return await self._message_repo.mark_message_delivered(message_id)

    async def mark_message_seen(self, message_id: str) -> bool:
        return await self._message_repo.mark_message_seen(message_id)

    async def delete_message(self, message_id: str, user_id: str) -> bool:
        """
        Delete (recall) a message. Only the sender can delete their own message.
        """
        return await self._message_repo.delete_message(message_id, user_id)

    async def should_push_offline(self, receiver_id: str) -> bool:
        bus = await get_bus()
        if getattr(bus, "enabled", False):
            try:
                r = bus._redis  # type: ignore
                ttl = await r.ttl(f"presence:{receiver_id}")
                return not (ttl and ttl > 0)
            except Exception:
                return True
        # No Redis → unknown presence; choose to push
        return True

    async def push_new_message(self, db, receiver_id: str, title: str, body: str, data: dict):
        push = await get_push()
        if not getattr(push, "enabled", False):
            return
        device_repo = DeviceRepository(db)
        tokens = await device_repo.get_tokens(receiver_id, platform="fcm")
        await push.send_fcm([t["token"] for t in tokens], title, body, data)

    async def send_fcm_notification_for_message(
        self,
        db,
        receiver_id: str,
        sender_id: str,
        message_content: str,
        conversation_id: str,
        is_group: bool = False,
        group_name: Optional[str] = None,
        is_encrypted: bool = False
    ):
        """
        Send FCM push notification to receiver when they receive a new message.
        Only sends if receiver is offline.
        """
        try:
            # Check if receiver is online
            is_offline = await self.should_push_offline(receiver_id)
            if not is_offline:
                logger.info(f"Receiver {receiver_id} is online, skipping FCM notification")
                return
            
            # Get FCM tokens for receiver
            fcm_repo = FCMTokenRepository(db)
            fcm_tokens = await fcm_repo.get_user_tokens(receiver_id)
            
            if not fcm_tokens:
                logger.info(f"No FCM tokens found for receiver {receiver_id}")
                return
            
            # **CRITICAL**: Verify conversation type from database to ensure accuracy
            # This prevents bugs where is_group flag might be incorrect
            convo = await self._conversation_repo.get_by_id(conversation_id)
            if convo:
                # Override is_group with actual value from database
                actual_is_group = convo.get("is_group", False)
                if actual_is_group != is_group:
                    logger.warning(
                        f"⚠️ Conversation type mismatch for {conversation_id}: "
                        f"passed is_group={is_group}, but database says is_group={actual_is_group}. "
                        f"Using database value."
                    )
                    is_group = actual_is_group
                
                # Get group name from database if not provided
                if is_group and not group_name:
                    group_name = convo.get("name", "Group")
            else:
                logger.warning(f"⚠️ Conversation {conversation_id} not found in database, using passed is_group={is_group}")
            
            # Get sender's name
            user_repo = UserRepository(db)
            sender = await user_repo.get_user_by_id(sender_id)
            sender_name = sender.get("full_name") or sender.get("email") or "Someone" if sender else "Someone"
            
            # Send notification to all tokens
            for token in fcm_tokens:
                await fcm_service.send_chat_message_notification(
                    fcm_token=token,
                    sender_name=sender_name,
                    message_content=message_content,
                    conversation_id=conversation_id,
                    is_group=is_group,
                    group_name=group_name,
                    sender_id=sender_id,
                    is_encrypted=is_encrypted
                )
            
            logger.info(
                f"✅ FCM notification sent to {len(fcm_tokens)} device(s) for receiver {receiver_id} "
                f"(conversation={conversation_id}, is_group={is_group})"
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to send FCM notification: {e}")
            # Don't raise exception - notification failure shouldn't break message sending

    async def delete_conversation(self, conversation_id: str, user_id: str, key_repo: ConversationKeyRepository = None) -> bool:
        """
        Xóa cuộc trò chuyện và tất cả messages liên quan cho user hiện tại.
        Cũng xóa tất cả conversation keys nếu có.
        """
        # Xóa conversation keys trước (nếu có)
        if key_repo:
            try:
                await key_repo.delete_keys_for_conversation(conversation_id)
            except Exception:
                pass  # Ignore errors khi xóa keys
        
        return await self._conversation_repo.delete_conversation(conversation_id, user_id, self._message_repo)

    async def create_conversation_with_keys(
        self,
        current_user_id: str,
        participant_id: str,
        key_repo: ConversationKeyRepository,
        encrypted_keys: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Tạo conversation mới và lưu encrypted keys đồng bộ.
        Đảm bảo cả conversation và keys đều được lưu thành công trước khi trả về.
        
        Args:
            current_user_id: ID của user hiện tại (người tạo conversation)
            participant_id: ID của người tham gia
            key_repo: Repository để lưu keys
            encrypted_keys: List of {user_id, encrypted_session_key}
        
        Returns:
            Dict với conversation_id và thông tin conversation
        """
        # Tạo conversation
        convo = await self._conversation_repo.get_or_create_one_to_one(current_user_id, participant_id)
        conversation_id = str(convo["_id"])
        
        # **CRITICAL**: Only store key for the current user (who is creating the conversation)
        # Do NOT overwrite keys for other users - they will upload their own keys
        # This prevents race conditions when both users create conversation simultaneously
        stored_count = 0
        for key_data in encrypted_keys:
            user_id = key_data.get("user_id")
            encrypted_key = key_data.get("encrypted_session_key")
            
            if not user_id or not encrypted_key:
                continue
            
            # Only store key for the current user
            # Other users will upload their own keys when they create conversation or receive first message
            if user_id == current_user_id:
                # Check if key already exists (to avoid overwriting if conversation was created by peer)
                existing_key = await key_repo.get_key(conversation_id, user_id)
                if existing_key is None:
                    # Key doesn't exist, safe to store
                    await key_repo.store_key(conversation_id, user_id, encrypted_key)
                    stored_count += 1
                else:
                    # Key already exists (peer may have created it), don't overwrite
                    # But still count as stored since key exists
                    stored_count += 1
                    logger.info(f"Key already exists for user {user_id} in conversation {conversation_id}, not overwriting")
            else:
                # For other users, only store if key doesn't exist
                # This allows the creator to provide keys for peer, but won't overwrite if peer already uploaded
                existing_key = await key_repo.get_key(conversation_id, user_id)
                if existing_key is None:
                    await key_repo.store_key(conversation_id, user_id, encrypted_key)
                    stored_count += 1
                else:
                    # Key already exists (peer uploaded their own), don't overwrite
                    logger.info(f"Key already exists for user {user_id} in conversation {conversation_id}, not overwriting")
        
        if stored_count == 0:
            raise ValueError("No valid keys provided or all keys already exist")
        
        return {
            "conversation_id": conversation_id,
            "participants": convo.get("participants", []),
            "created_at": convo.get("last_message_at")
        }


