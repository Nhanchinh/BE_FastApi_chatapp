from typing import List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase


class UserRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db.get_collection("users")

    async def create_user(self, email: str, hashed_password: str, full_name: Optional[str], role: str = "user") -> str:

        doc = {
            "email": email,
            "hashed_password": hashed_password,
            "full_name": full_name,
            "role": role
        }
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


