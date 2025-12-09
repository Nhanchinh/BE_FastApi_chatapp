from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING


class ConversationRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db["conversations"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("participants", ASCENDING)])
        await self.collection.create_index([("last_message_at", DESCENDING)])
        await self.collection.create_index([("is_group", ASCENDING)])

    async def get_or_create_one_to_one(self, user_a: str, user_b: str) -> Dict[str, Any]:
        participants = sorted([user_a, user_b])
        existing = await self.collection.find_one({"participants": participants})
        if existing:
            existing["_id"] = str(existing.get("_id"))
            return existing
        doc: Dict[str, Any] = {
            "participants": participants,
            "last_message_at": datetime.now(timezone.utc),
            "last_message_preview": None,
            "unread_counters": {user_a: 0, user_b: 0},
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc

    async def update_on_new_message(self, conversation_id, preview: str, receiver_id: str, sender_id: str) -> None:
        await self.collection.update_one(
            {"_id": conversation_id},
            {
                "$set": {
                    "last_message_at": datetime.now(timezone.utc),
                    "last_message_preview": preview,
                    "last_message_sender_id": sender_id,  # Lưu sender_id của last message
                },
                "$inc": {f"unread_counters.{receiver_id}": 1},
            },
        )

    async def update_on_new_group_message(self, conversation_id, preview: str, sender_id: str, participants: list[str]) -> None:
        inc_fields = {f"unread_counters.{uid}": 1 for uid in participants if uid != sender_id}
        await self.collection.update_one(
            {"_id": conversation_id},
            {
                "$set": {
                    "last_message_at": datetime.now(timezone.utc),
                    "last_message_preview": preview,
                    "last_message_sender_id": sender_id,
                },
                "$inc": inc_fields,
            },
        )

    async def reset_unread(self, conversation_id, user_id: str) -> None:
        await self.collection.update_one(
            {"_id": conversation_id},
            {"$set": {f"unread_counters.{user_id}": 0}},
        )

    async def list_for_user(self, user_id: str, limit: int = 20, cursor: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        query = {"participants": {"$in": [user_id]}}
        sort = [("last_message_at", DESCENDING), ("_id", DESCENDING)]
        if cursor:
            # Cursor format: timestamp_ms:object_id_hex
            try:
                ts_str, oid_hex = cursor.split(":", 1)
                ts = datetime.fromtimestamp(int(ts_str) / 1000.0, tz=timezone.utc)
                query["$or"] = [
                    {"last_message_at": {"$lt": ts}},
                    {"last_message_at": ts, "_id": {"$lt": self._to_object_id(oid_hex)}},
                ]
            except Exception:
                pass

        cursor_db = self.collection.find(query).sort(sort).limit(limit)
        items = await cursor_db.to_list(length=limit)
        for it in items:
            it["_id"] = str(it.get("_id"))
        next_cursor = None
        if items:
            last = items[-1]
            last_ts = int(last["last_message_at"].timestamp() * 1000)
            next_cursor = f"{last_ts}:{last['_id']}"
        return items, next_cursor

    def _to_object_id(self, oid_hex: str):
        from bson import ObjectId
        return ObjectId(oid_hex)

    async def delete_conversation(self, conversation_id: str, user_id: str, message_repo=None) -> bool:
        """
        Xóa cuộc trò chuyện và tất cả messages liên quan. Chỉ xóa nếu user là participant.
        """
        from bson import ObjectId
        oid = ObjectId(conversation_id) if isinstance(conversation_id, str) else conversation_id
        
        # Kiểm tra xem user có trong conversation không
        conversation = await self.collection.find_one({"_id": oid})
        if not conversation:
            return False
        
        # Kiểm tra user có phải là participant không
        if user_id not in conversation.get("participants", []):
            return False
        
        # Xóa tất cả messages trong conversation trước
        if message_repo:
            try:
                await message_repo.collection.delete_many({"conversation_id": oid})
            except Exception:
                pass  # Ignore errors khi xóa messages
        
        # Xóa conversation
        result = await self.collection.delete_one({"_id": oid})
        return result.deleted_count > 0

    async def get_by_id(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        from bson import ObjectId
        try:
            oid = ObjectId(conversation_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"_id": oid})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def create_group(self, name: str, participants: list[str], owner_id: str) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "name": name,
            "is_group": True,
            "participants": participants,
            "last_message_at": datetime.now(timezone.utc),
            "last_message_preview": None,
            "unread_counters": {uid: 0 for uid in participants},
            "group_key_version": 1,
            "owner_id": owner_id,
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc

    async def add_members(self, conversation_id, new_members: list[str]) -> Dict[str, Any] | None:
        update = {
            "$addToSet": {"participants": {"$each": new_members}},
            "$set": {f"unread_counters.{uid}": 0 for uid in new_members},
        }
        res = await self.collection.update_one({"_id": conversation_id}, update)
        if res.matched_count == 0:
            return None
        return await self.get_by_id(str(conversation_id))

    async def remove_member(self, conversation_id, member_id: str) -> bool:
        res = await self.collection.update_one(
            {"_id": conversation_id},
            {
                "$pull": {"participants": member_id},
                "$unset": {f"unread_counters.{member_id}": ""},
            },
        )
        return res.modified_count > 0

    async def set_owner(self, conversation_id, owner_id: str) -> bool:
        res = await self.collection.update_one(
            {"_id": conversation_id},
            {"$set": {"owner_id": owner_id}},
        )
        return res.modified_count > 0


