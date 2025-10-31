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

    async def update_on_new_message(self, conversation_id, preview: str, receiver_id: str) -> None:
        await self.collection.update_one(
            {"_id": conversation_id},
            {
                "$set": {
                    "last_message_at": datetime.now(timezone.utc),
                    "last_message_preview": preview,
                },
                "$inc": {f"unread_counters.{receiver_id}": 1},
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


