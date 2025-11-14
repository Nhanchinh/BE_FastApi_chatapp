from typing import List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING


class UserRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db.get_collection("users")

    async def create_user(self, email: str, hashed_password: str, full_name: Optional[str], role: str = "user", public_key: Optional[str] = None) -> str:

        doc = {
            "email": email,
            "hashed_password": hashed_password,
            "full_name": full_name,
            "role": role
        }
        if public_key:
            doc["public_key"] = public_key
        result = await self._collection.insert_one(doc)
        return str(result.inserted_id)

    async def get_user_by_email(self, email: str) -> Optional[dict]:

        user = await self._collection.find_one({"email": email})
        if user:
            user["_id"] = str(user["_id"])  # normalize to string for API layer
        return user

    async def get_user_by_id(self, user_id: str) -> Optional[dict]:

        user = await self._collection.find_one({"_id": ObjectId(user_id)})
        if user:
            user["_id"] = str(user["_id"])
        return user

    async def get_all_users(self) -> List[dict]:

        users = []
        async for user in self._collection.find():
            user["_id"] = str(user["_id"])
            users.append(user)
        return users

    async def delete_user(self, user_id: str) -> bool:

        result = await self._collection.delete_one({"_id": ObjectId(user_id)})
        return result.deleted_count > 0

    async def update_user_profile(self, user_id: str, updates: dict) -> bool:
        """Cập nhật thông tin profile của user"""
        # Chỉ cho phép update các trường an toàn
        allowed_fields = ["full_name", "location", "hometown", "birth_year", "public_key"]
        filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields and v is not None}
        
        if not filtered_updates:
            return False
        
        result = await self._collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": filtered_updates}
        )
        return result.modified_count > 0

    async def get_users_by_ids(self, user_ids: List[str]) -> List[dict]:
        if not user_ids:
            return []
        object_ids = [ObjectId(uid) for uid in user_ids]
        users: List[dict] = []
        async for user in self._collection.find({"_id": {"$in": object_ids}}):
            user["_id"] = str(user["_id"])  # normalize for API layer
            users.append(user)
        return users

    async def search_users_by_name(self, query: str, limit: int = 20, prefix: bool = False) -> List[dict]:
        if not query:
            return []
        pattern = f"^{query}" if prefix else query
        regex = {"$regex": pattern, "$options": "i"}
        cursor = self._collection.find({"full_name": regex}).sort("full_name", ASCENDING).limit(int(limit))
        users: List[dict] = []
        async for user in cursor:
            user["_id"] = str(user["_id"])  # normalize
            users.append(user)
        return users

    async def update_last_seen(self, user_id: str) -> bool:
        """Cập nhật last_seen timestamp khi user offline"""
        from datetime import datetime, timezone
        try:
            result = await self._collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"last_seen": datetime.now(timezone.utc).isoformat()}}
            )
            return result.modified_count > 0
        except Exception:
            return False


