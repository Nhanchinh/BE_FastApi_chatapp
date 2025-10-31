from datetime import datetime, timezone
from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorDatabase


class DeviceRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db["devices"]

    async def register(self, user_id: str, platform: str, token: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        await self.collection.update_one(
            {"user_id": user_id, "platform": platform, "token": token},
            {"$set": {"last_seen_at": now}},
            upsert=True,
        )
        return {"user_id": user_id, "platform": platform, "token": token}

    async def get_tokens(self, user_id: str, platform: str | None = None) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": user_id}
        if platform:
            query["platform"] = platform
        cur = self.collection.find(query)
        items = await cur.to_list(length=100)
        return items


