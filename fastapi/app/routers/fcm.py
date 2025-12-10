from fastapi import APIRouter, Depends, HTTPException
from app.models.fcm_token import FCMTokenRequest, FCMTokenResponse
from app.repositories.fcm_token_repository import FCMTokenRepository
from app.database.connection import mongo_db_dependency
from app.utils.dependencies import get_current_user
from motor.motor_asyncio import AsyncIOMotorDatabase
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/fcm", tags=["FCM"])

@router.post("/token", response_model=FCMTokenResponse)
async def register_fcm_token(
    request: FCMTokenRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(mongo_db_dependency)
):
    """
    Register or update FCM token for the current user
    """
    user_id = str(current_user["_id"])  # Fix: use "_id" not "user_id"
    logger.info(f"📥 Received FCM token registration request from user: {user_id}")
    logger.info(f"   Token: {request.fcm_token[:20]}... (truncated)")
    logger.info(f"   Device ID: {request.device_id}")
    logger.info(f"   Device Type: {request.device_type}")
    
    fcm_repo = FCMTokenRepository(db)
    
    success = await fcm_repo.store_token(
        user_id=user_id,
        fcm_token=request.fcm_token,
        device_id=request.device_id,
        device_type=request.device_type
    )
    
    if success:
        logger.info(f"✅ FCM token registered successfully for user {user_id}")
        return FCMTokenResponse(
            success=True,
            message="FCM token registered successfully"
        )
    else:
        logger.error(f"❌ Failed to register FCM token for user {user_id}")
        raise HTTPException(status_code=500, detail="Failed to register FCM token")

@router.delete("/token")
async def deactivate_fcm_token(
    fcm_token: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(mongo_db_dependency)
):
    """
    Deactivate a specific FCM token (e.g., on logout)
    """
    fcm_repo = FCMTokenRepository(db)
    success = await fcm_repo.deactivate_token(fcm_token)
    
    if success:
        return {"success": True, "message": "FCM token deactivated"}
    else:
        return {"success": False, "message": "FCM token not found or already inactive"}

@router.delete("/tokens/all")
async def deactivate_all_tokens(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(mongo_db_dependency)
):
    """
    Deactivate all FCM tokens for the current user (e.g., logout from all devices)
    """
    user_id = str(current_user["_id"])  # Fix: use "_id" not "user_id"
    fcm_repo = FCMTokenRepository(db)
    success = await fcm_repo.deactivate_user_tokens(user_id)
    
    if success:
        return {"success": True, "message": "All FCM tokens deactivated"}
    else:
        return {"success": False, "message": "No active tokens found"}

