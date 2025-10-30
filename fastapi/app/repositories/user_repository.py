from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase


class UserRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db.get_collection("users")

    async def create_user(self, email: str, hashed_password: str, full_name: Optional[str]) -> str:

        doc = {"email": email, "hashed_password": hashed_password, "full_name": full_name}
        result = await self._collection.insert_one(doc)
        return str(result.inserted_id)

    async def get_user_by_email(self, email: str) -> Optional[dict]:

        user = await self._collection.find_one({"email": email})
        if user:
            user["_id"] = str(user["_id"])  # normalize to string for API layer
        return user


