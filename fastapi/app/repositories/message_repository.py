from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from bson import ObjectId

from motor.motor_asyncio import AsyncIOMotorDatabase


def convert_objectid_to_str(obj: Any) -> Any:
    """Recursively convert all ObjectId instances to strings in a dict/list structure."""
    if isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: convert_objectid_to_str(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_objectid_to_str(item) for item in obj]
    else:
        return obj


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
        iv: Optional[str] = None,
        is_encrypted: bool = False,
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
        # Add E2EE fields if present
        if iv:
            doc["iv"] = iv
        if is_encrypted:
            doc["is_encrypted"] = is_encrypted
        result = await self.collection.insert_one(doc)
        # Build API-facing dict with string ids
        api_doc = dict(doc)
        api_doc["_id"] = str(result.inserted_id)
        # Recursively convert all ObjectId to string
        api_doc = convert_objectid_to_str(api_doc)
        return api_doc

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
        # Recursively convert all ObjectId to string in each item
        items = [convert_objectid_to_str(item) for item in items]
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
        # Recursively convert all ObjectId to string in each item
        items = [convert_objectid_to_str(item) for item in items]
        return items

    async def get_for_receiver_since(self, user_id: str, since_ts_ms: int) -> List[Dict[str, Any]]:
        since = datetime.fromtimestamp(since_ts_ms / 1000.0, tz=timezone.utc)
        cursor = self.collection.find({"receiver_id": user_id, "timestamp": {"$gt": since}}).sort("timestamp", 1)
        items = await cursor.to_list(length=1000)
        # Recursively convert all ObjectId to string in each item
        items = [convert_objectid_to_str(item) for item in items]
        return items

    async def mark_read(self, receiver_id: str, from_user_id: Optional[str] = None, conversation_id: Optional[str] = None) -> int:
        query: Dict[str, Any] = {"receiver_id": receiver_id, "seen": False}
        if from_user_id:
            query["sender_id"] = from_user_id
        if conversation_id:
            try:
                conv_oid = ObjectId(conversation_id)
            except Exception:
                conv_oid = conversation_id  # type: ignore[assignment]
            query["conversation_id"] = conv_oid  # match stored type
        result = await self.collection.update_many(query, {"$set": {"seen": True}})
        return result.modified_count or 0

    async def mark_delivered_for_receiver(self, conversation_id, receiver_id: str) -> int:
        try:
            conv_oid = ObjectId(conversation_id)
        except Exception:
            conv_oid = conversation_id  # type: ignore[assignment]
        result = await self.collection.update_many(
            {"conversation_id": conv_oid, "receiver_id": receiver_id, "delivered": False},
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


