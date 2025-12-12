from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import OperationFailure


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _convert(doc: dict) -> dict:
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    if "created_at" in out:
        out["created_at"] = _to_iso(out.get("created_at"))
    return out


class NotificationRepository:
    _indexes_initialized: bool = False

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db.get_collection("notifications")

    async def _ensure_indexes(self) -> None:
        if NotificationRepository._indexes_initialized:
            return
        await self._collection.create_index("user_id", name="idx_notifications_user")
        # TTL 3 ngày (259200 giây) - idempotent even if existed with same name
        try:
            await self._collection.create_index(
                "created_at",
                expireAfterSeconds=259200,
                name="idx_notifications_ttl_created_at",
            )
        except OperationFailure as e:
            # Ignore if same index already exists with different generated name
            if e.code != 85:
                raise
        await self._collection.create_index(
            [("user_id", 1), ("created_at", -1)],
            name="idx_notifications_user_created_at_desc",
        )
        NotificationRepository._indexes_initialized = True

    async def create_notification(
        self,
        user_id: str,
        title: str,
        body: str,
        notif_type: str,
        from_user_id: Optional[str] = None,
        from_user_name: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> str:
        await self._ensure_indexes()
        doc: Dict[str, Any] = {
            "user_id": user_id,
            "title": title,
            "body": body,
            "type": notif_type,
            "from_user_id": from_user_id,
            "from_user_name": from_user_name,
            "data": data or {},
            "is_read": False,
            "created_at": datetime.now(timezone.utc),
        }
        result = await self._collection.insert_one(doc)
        return str(result.inserted_id)

    async def list_notifications(
        self, user_id: str, limit: int = 6, cursor: Optional[str] = None
    ) -> Tuple[List[dict], Optional[str]]:
        await self._ensure_indexes()
        query: Dict[str, Any] = {"user_id": user_id}
        sort = [("created_at", -1), ("_id", -1)]

        if cursor:
            # cursor format: ts_ms:oid
            try:
                ts_str, oid_hex = cursor.split(":", 1)
                ts = datetime.fromtimestamp(int(ts_str) / 1000.0, tz=timezone.utc)
                query["$or"] = [
                    {"created_at": {"$lt": ts}},
                    {"created_at": ts, "_id": {"$lt": ObjectId(oid_hex)}},
                ]
            except Exception:
                pass

        cur = (
            self._collection.find(query)
            .sort(sort)
            .limit(limit)
        )
        items = await cur.to_list(length=limit)
        items = [_convert(item) for item in items]

        next_cursor = None
        if items:
            last = items[-1]
            created_at = last.get("created_at")
            if created_at and isinstance(created_at, str):
                try:
                    ts_ms = int(datetime.fromisoformat(created_at).timestamp() * 1000)
                    next_cursor = f"{ts_ms}:{last['_id']}"
                except Exception:
                    pass
        return items, next_cursor

    async def mark_read(self, notification_id: str, user_id: str) -> bool:
        await self._ensure_indexes()
        result = await self._collection.update_one(
            {"_id": ObjectId(notification_id), "user_id": user_id},
            {"$set": {"is_read": True}},
        )
        return result.modified_count > 0

    async def mark_all_read(self, user_id: str) -> int:
        await self._ensure_indexes()
        result = await self._collection.update_many(
            {"user_id": user_id, "is_read": False}, {"$set": {"is_read": True}}
        )
        return result.modified_count

    async def count_unread(self, user_id: str) -> int:
        await self._ensure_indexes()
        return await self._collection.count_documents({"user_id": user_id, "is_read": False})

