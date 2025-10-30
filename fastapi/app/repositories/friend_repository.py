from typing import Optional
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

class FriendRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db.get_collection("friend_requests")
        self._user_collection = db.get_collection("users")

    async def create_friend_request(self, from_user: str, to_user: str) -> str:
        doc = {
            "from_user": from_user,
            "to_user": to_user,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }
        result = await self._collection.insert_one(doc)
        return str(result.inserted_id)

    async def get_friend_request(self, from_user: str, to_user: str) -> Optional[dict]:
        doc = await self._collection.find_one({"from_user": from_user, "to_user": to_user})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])  # normalize for API layer
        return doc

    async def update_request_status(self, request_id: str, status: str) -> bool:
        result = await self._collection.update_one({"_id": ObjectId(request_id)}, {"$set": {"status": status}})
        return result.modified_count > 0

    async def delete_friend_request(self, request_id: str) -> bool:
        result = await self._collection.delete_one({"_id": ObjectId(request_id)})
        return result.deleted_count > 0

    async def list_received_requests(self, user_id: str):
        cursor = self._collection.find({"to_user": user_id, "status": "pending"})
        results = []
        async for doc in cursor:
            results.append({
                "id": str(doc.get("_id")),
                "from_user": doc.get("from_user"),
                "to_user": doc.get("to_user"),
                "status": doc.get("status"),
                "created_at": doc.get("created_at"),
            })
        return results

    async def list_friends(self, user_id: str):
        user = await self._user_collection.find_one({"_id": ObjectId(user_id)})
        return user.get("friends", []) if user else []

    async def unfriend(self, user_id: str, friend_id: str) -> bool:
        # remove each other from friends array
        res1 = await self._user_collection.update_one(
            {"_id": ObjectId(user_id)}, {"$pull": {"friends": friend_id}}
        )
        res2 = await self._user_collection.update_one(
            {"_id": ObjectId(friend_id)}, {"$pull": {"friends": user_id}}
        )
        return (res1.modified_count + res2.modified_count) > 0
