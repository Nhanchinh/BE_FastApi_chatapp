from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase


class RefreshTokenRepository:
    """Quản lý refresh tokens lưu trong MongoDB."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db.get_collection("refresh_tokens")

    async def create_refresh_token(
        self,
        user_id: str,
        token_id: str,
        hashed_secret: str,
        expires_at: datetime,
    ) -> str:
        doc = {
            "user_id": user_id,
            "token_id": token_id,
            "hashed_secret": hashed_secret,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc),
            "revoked": False,
        }
        result = await self._collection.insert_one(doc)
        return str(result.inserted_id)

    async def get_active_token(self, token_id: str) -> Optional[dict]:
        doc = await self._collection.find_one(
            {"token_id": token_id, "revoked": False}
        )
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def revoke_token(self, token_id: str) -> None:
        await self._collection.update_many(
            {"token_id": token_id, "revoked": False},
            {"$set": {"revoked": True, "revoked_at": datetime.now(timezone.utc)}},
        )

    async def revoke_all_for_user(self, user_id: str) -> None:
        await self._collection.update_many(
            {"user_id": user_id, "revoked": False},
            {"$set": {"revoked": True, "revoked_at": datetime.now(timezone.utc)}},
        )

    async def prune_expired(self) -> int:
        """Xoá token đã hết hạn."""
        now = datetime.now(timezone.utc)
        result = await self._collection.delete_many({"expires_at": {"$lt": now}})
        return int(result.deleted_count)

