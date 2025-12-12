from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional, List
from datetime import datetime
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class FCMTokenRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db["fcm_tokens"]

    async def store_token(
        self,
        user_id: str,
        fcm_token: str,
        device_id: Optional[str] = None,
        device_type: str = "android"
    ) -> bool:
        """
        Store or update FCM token for a user
        If token already exists, update it. Otherwise, create new.
        """
        try:
            logger.info(f"🔍 Checking if FCM token exists for user {user_id}")
            
            # Check if this token already exists for this user
            existing = await self.collection.find_one({
                "user_id": user_id,
                "fcm_token": fcm_token
            })

            if existing:
                logger.info(f"♻️  Updating existing FCM token for user {user_id}")
                # Update existing token
                result = await self.collection.update_one(
                    {"_id": existing["_id"]},
                    {
                        "$set": {
                            "device_id": device_id,
                            "device_type": device_type,
                            "updated_at": datetime.utcnow(),
                            "is_active": True
                        }
                    }
                )
                logger.info(f"   Modified count: {result.modified_count}")
            else:
                logger.info(f"➕ Inserting new FCM token for user {user_id}")
                
                # Deactivate ALL old tokens for this user (not just same device_id)
                # This handles the case when app is reinstalled and gets a new token
                deactivate_result = await self.collection.update_many(
                    {"user_id": user_id, "is_active": True},
                    {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
                )
                logger.info(f"   Deactivated {deactivate_result.modified_count} old token(s) for user {user_id}")
                
                # Also deactivate tokens for the same device_id if provided (for multi-device scenarios)
                if device_id:
                    device_deactivate_result = await self.collection.update_many(
                        {"user_id": user_id, "device_id": device_id, "is_active": True},
                        {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
                    )
                    if device_deactivate_result.modified_count > 0:
                        logger.info(f"   Deactivated {device_deactivate_result.modified_count} additional token(s) for device {device_id}")

                # Insert new token
                doc = {
                    "user_id": user_id,
                    "fcm_token": fcm_token,
                    "device_id": device_id,
                    "device_type": device_type,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "is_active": True
                }
                result = await self.collection.insert_one(doc)
                logger.info(f"   Inserted with ID: {result.inserted_id}")

            # Verify insertion
            count = await self.collection.count_documents({"user_id": user_id, "is_active": True})
            logger.info(f"✅ User {user_id} now has {count} active FCM token(s)")
            
            return True
        except Exception as e:
            logger.error(f"❌ Error storing FCM token for user {user_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def get_user_tokens(self, user_id: str) -> List[str]:
        """
        Get all active FCM tokens for a user
        Returns list of FCM token strings
        """
        try:
            cursor = self.collection.find({
                "user_id": user_id,
                "is_active": True
            })
            tokens = []
            async for doc in cursor:
                tokens.append(doc["fcm_token"])
            return tokens
        except Exception as e:
            print(f"Error getting user tokens: {e}")
            return []

    async def get_tokens_for_users(self, user_ids: List[str]) -> dict[str, List[str]]:
        """
        Get FCM tokens for multiple users
        Returns dict mapping user_id -> list of FCM tokens
        """
        try:
            cursor = self.collection.find({
                "user_id": {"$in": user_ids},
                "is_active": True
            })
            
            tokens_map = {uid: [] for uid in user_ids}
            async for doc in cursor:
                user_id = doc["user_id"]
                if user_id in tokens_map:
                    tokens_map[user_id].append(doc["fcm_token"])
            
            return tokens_map
        except Exception as e:
            print(f"Error getting tokens for users: {e}")
            return {uid: [] for uid in user_ids}

    async def deactivate_token(self, fcm_token: str) -> bool:
        """
        Deactivate a specific FCM token (e.g., on logout)
        """
        try:
            result = await self.collection.update_many(
                {"fcm_token": fcm_token},
                {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error deactivating token: {e}")
            return False

    async def deactivate_user_tokens(self, user_id: str) -> bool:
        """
        Deactivate all tokens for a user (e.g., on logout from all devices)
        """
        try:
            result = await self.collection.update_many(
                {"user_id": user_id},
                {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error deactivating user tokens: {e}")
            return False

    async def delete_token(self, fcm_token: str) -> bool:
        """
        Permanently delete a FCM token
        """
        try:
            result = await self.collection.delete_many({"fcm_token": fcm_token})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting token: {e}")
            return False

