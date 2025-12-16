from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.database.connection import mongo_db_dependency
from app.repositories.key_backup_repository import KeyBackupRepository
from app.utils.dependencies import get_current_user


router = APIRouter(prefix="/key-backup", tags=["e2ee"])


class CreateBackupRequest(BaseModel):
    """Request to create/update encrypted key backup"""
    encrypted_backup: str   # Base64-encoded AES-GCM encrypted data
    salt: str               # Base64-encoded PBKDF2 salt
    iv: str                 # Base64-encoded AES-GCM IV
    conversation_ids: List[str]  # List of conversation IDs included in backup


class GetBackupResponse(BaseModel):
    """Response containing encrypted key backup"""
    encrypted_backup: str
    salt: str
    iv: str
    conversation_ids: List[str]
    updated_at: str


def get_backup_repo(db=Depends(mongo_db_dependency)) -> KeyBackupRepository:
    return KeyBackupRepository(db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_or_update_backup(
    payload: CreateBackupRequest,
    current_user: dict = Depends(get_current_user),
    repo: KeyBackupRepository = Depends(get_backup_repo)
):
    """
    Create or update the encrypted key backup for the current user.
    The backup contains all conversation AES keys encrypted with a PIN-derived key.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = current_user["_id"]
    logger.info(f"[KEY_BACKUP] User {user_id} creating/updating backup with {len(payload.conversation_ids)} conversations")
    
    if not payload.encrypted_backup or not payload.salt or not payload.iv:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: encrypted_backup, salt, iv"
        )
    
    doc_id = await repo.create_or_update(
        user_id=user_id,
        encrypted_backup=payload.encrypted_backup,
        salt=payload.salt,
        iv=payload.iv,
        conversation_ids=payload.conversation_ids
    )
    
    logger.info(f"[KEY_BACKUP] ✅ Backup saved for user {user_id}, doc_id: {doc_id}")
    
    return {
        "message": "Backup created/updated successfully",
        "conversation_count": len(payload.conversation_ids)
    }


@router.get("", response_model=GetBackupResponse)
async def get_backup(
    current_user: dict = Depends(get_current_user),
    repo: KeyBackupRepository = Depends(get_backup_repo)
):
    """
    Get the encrypted key backup for the current user.
    Returns 404 if no backup exists.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = current_user["_id"]
    logger.info(f"[KEY_BACKUP] User {user_id} fetching their backup")
    
    backup = await repo.get_by_user(user_id)
    
    if not backup:
        logger.info(f"[KEY_BACKUP] No backup found for user {user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No backup found"
        )
    
    logger.info(f"[KEY_BACKUP] ✅ Backup found for user {user_id} with {len(backup.get('conversation_ids', []))} conversations")
    
    return GetBackupResponse(
        encrypted_backup=backup["encrypted_backup"],
        salt=backup["salt"],
        iv=backup["iv"],
        conversation_ids=backup.get("conversation_ids", []),
        updated_at=backup["updated_at"]
    )


@router.get("/exists")
async def check_backup_exists(
    current_user: dict = Depends(get_current_user),
    repo: KeyBackupRepository = Depends(get_backup_repo)
):
    """
    Check if a backup exists for the current user.
    Used to determine if restore flow should be shown after login.
    """
    user_id = current_user["_id"]
    backup = await repo.get_by_user(user_id)
    
    return {
        "exists": backup is not None,
        "conversation_count": len(backup.get("conversation_ids", [])) if backup else 0
    }


@router.delete("")
async def delete_backup(
    current_user: dict = Depends(get_current_user),
    repo: KeyBackupRepository = Depends(get_backup_repo)
):
    """
    Delete the key backup for the current user.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = current_user["_id"]
    logger.info(f"[KEY_BACKUP] User {user_id} deleting their backup")
    
    deleted = await repo.delete_by_user(user_id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No backup found to delete"
        )
    
    logger.info(f"[KEY_BACKUP] ✅ Backup deleted for user {user_id}")
    
    return {"message": "Backup deleted successfully"}
