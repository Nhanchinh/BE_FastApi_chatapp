from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from bson import ObjectId

from motor.motor_asyncio import AsyncIOMotorDatabase


class MessageRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db["messages"]

    async def save_message(
        self,
        conversation_id,
        sender_id: str,
        receiver_id: str,
        content: str,
        client_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "content": content,
            "timestamp": datetime.now(timezone.utc),
            "delivered": False,
            "seen": False,
            "client_message_id": client_message_id,
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc

    async def get_messages_by_conversation(
        self,
        conversation_id,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        query: Dict[str, Any] = {"conversation_id": conversation_id}
        sort = [("timestamp", -1), ("_id", -1)]
        if cursor:
            # cursor format: ts_ms:oid
            try:
                ts_str, oid_hex = cursor.split(":", 1)
                from bson import ObjectId
                ts = datetime.fromtimestamp(int(ts_str) / 1000.0, tz=timezone.utc)
                query["$or"] = [
                    {"timestamp": {"$lt": ts}},
                    {"timestamp": ts, "_id": {"$lt": ObjectId(oid_hex)}},
                ]
            except Exception:
                pass
        cur = self.collection.find(query).sort(sort).limit(limit)
        items = await cur.to_list(length=limit)
        for it in items:
            it["_id"] = str(it.get("_id"))
        next_cursor = None
        if items:
            last = items[-1]
            last_ts = int(last["timestamp"].timestamp() * 1000)
            next_cursor = f"{last_ts}:{last['_id']}"
        # return ascending chronological order for UI if needed
        return list(reversed(items)), next_cursor

    async def get_unread(self, user_id: str, from_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"receiver_id": user_id, "seen": False}
        if from_user_id:
            query["sender_id"] = from_user_id
        cursor = self.collection.find(query).sort("timestamp", 1)
        items = await cursor.to_list(length=1000)
        for it in items:
            it["_id"] = str(it.get("_id"))
        return items

    async def get_for_receiver_since(self, user_id: str, since_ts_ms: int) -> List[Dict[str, Any]]:
        since = datetime.fromtimestamp(since_ts_ms / 1000.0, tz=timezone.utc)
        cursor = self.collection.find({"receiver_id": user_id, "timestamp": {"$gt": since}}).sort("timestamp", 1)
        items = await cursor.to_list(length=1000)
        for it in items:
            it["_id"] = str(it.get("_id"))
        return items

    async def mark_read(self, receiver_id: str, from_user_id: Optional[str] = None, conversation_id: Optional[str] = None) -> int:
        query: Dict[str, Any] = {"receiver_id": receiver_id, "seen": False}
        if from_user_id:
            query["sender_id"] = from_user_id
        if conversation_id:
            query["conversation_id"] = conversation_id
        result = await self.collection.update_many(query, {"$set": {"seen": True}})
        return result.modified_count or 0

    async def mark_delivered_for_receiver(self, conversation_id, receiver_id: str) -> int:
        result = await self.collection.update_many(
            {"conversation_id": conversation_id, "receiver_id": receiver_id, "delivered": False},
            {"$set": {"delivered": True}},
        )
        return result.modified_count or 0

    async def mark_message_delivered(self, message_id: str) -> bool:
        result = await self.collection.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"delivered": True}}
        )
        return bool(result.modified_count)

    async def mark_message_seen(self, message_id: str) -> bool:
        result = await self.collection.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"seen": True}}
        )
        return bool(result.modified_count)


