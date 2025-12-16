from datetime import datetime, timezone
from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase


class KeyBackupRepository:
    """Repository for managing encrypted key backups (one per user)"""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db["key_backups"]

    async def ensure_indexes(self) -> None:
        """Create indexes for efficient queries"""
        await self.collection.create_index([("user_id", 1)], unique=True)

    async def create_or_update(
        self,
        user_id: str,
        encrypted_backup: str,
        salt: str,
        iv: str,
        conversation_ids: List[str]
    ) -> str:
        """
        Create or update the encrypted key backup for a user.
        Each user can only have one backup.
        Returns the document ID.
        """
        now = datetime.now(timezone.utc).isoformat()
        
        doc = {
            "user_id": user_id,
            "encrypted_backup": encrypted_backup,
            "salt": salt,
            "iv": iv,
            "conversation_ids": conversation_ids,
            "updated_at": now,
        }
        
        # Check if backup exists
        existing = await self.collection.find_one({"user_id": user_id})
        
        if existing:
            # Update existing backup
            await self.collection.update_one(
                {"user_id": user_id},
                {"$set": doc}
            )
            return str(existing["_id"])
        else:
            # Create new backup
            doc["created_at"] = now
            result = await self.collection.insert_one(doc)
            return str(result.inserted_id)

    async def get_by_user(self, user_id: str) -> Optional[dict]:
        """Get the encrypted key backup for a user"""
        doc = await self.collection.find_one({"user_id": user_id})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def delete_by_user(self, user_id: str) -> bool:
        """Delete the key backup for a user. Returns True if deleted."""
        result = await self.collection.delete_one({"user_id": user_id})
        return result.deleted_count > 0
