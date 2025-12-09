from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase


class ConversationKeyRepository:
    """Repository for managing encrypted session keys per user per conversation"""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db["conversation_keys"]

    async def ensure_indexes(self) -> None:
        """Create indexes for efficient queries"""
        await self.collection.create_index([("conversation_id", 1), ("user_id", 1)], unique=True)
        await self.collection.create_index([("conversation_id", 1)])
        await self.collection.create_index([("user_id", 1)])

    async def store_key(self, conversation_id: str, user_id: str, encrypted_session_key: str, version: int = 1) -> str:
        """
        Store or update an encrypted session key for a user in a conversation.
        Returns the document ID.
        """
        doc = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "encrypted_session_key": encrypted_session_key,
            "version": version,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Upsert: update if exists, insert if not
        result = await self.collection.update_one(
            {"conversation_id": conversation_id, "user_id": user_id, "version": version},
            {"$set": doc},
            upsert=True
        )
        
        if result.upserted_id:
            return str(result.upserted_id)
        else:
            # Find the existing document
            existing = await self.collection.find_one({"conversation_id": conversation_id, "user_id": user_id})
            return str(existing["_id"]) if existing else ""

    async def get_key(self, conversation_id: str, user_id: str) -> Optional[dict]:
        """Get the encrypted session key for a specific user in a conversation"""
        doc = await self.collection.find_one({"conversation_id": conversation_id, "user_id": user_id}, sort=[("version", -1)])
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def get_keys_for_version(self, conversation_id: str, version: int) -> List[dict]:
        results = []
        async for doc in self.collection.find({"conversation_id": conversation_id, "version": version}):
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def get_keys_for_conversation(self, conversation_id: str) -> List[dict]:
        """Get all encrypted session keys for a conversation (for all participants)"""
        results = []
        async for doc in self.collection.find({"conversation_id": conversation_id}):
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def delete_keys_for_conversation(self, conversation_id: str) -> int:
        """Delete all keys for a conversation"""
        result = await self.collection.delete_many({"conversation_id": conversation_id})
        return result.deleted_count

