from typing import Any, Dict, List, Optional
import logging

from bson import ObjectId
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.conversation_key_repository import ConversationKeyRepository
from app.repositories.device_repository import DeviceRepository
from app.utils.notifications import get_push
from app.utils.realtime_bus import get_bus

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
        
        # Lưu encrypted keys cho tất cả participants
        stored_count = 0
        for key_data in encrypted_keys:
            user_id = key_data.get("user_id")
            encrypted_key = key_data.get("encrypted_session_key")
            
            if not user_id or not encrypted_key:
                continue
            
            await key_repo.store_key(conversation_id, user_id, encrypted_key)
            stored_count += 1
        
        if stored_count == 0:
            raise ValueError("No valid keys provided")
        
        return {
            "conversation_id": conversation_id,
            "participants": convo.get("participants", []),
            "created_at": convo.get("last_message_at")
        }


