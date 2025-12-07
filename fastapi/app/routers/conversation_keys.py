from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.database.connection import mongo_db_dependency
from app.repositories.conversation_key_repository import ConversationKeyRepository
from app.utils.dependencies import get_current_user


router = APIRouter(prefix="/conversation-keys", tags=["e2ee"])


class StoreKeyRequest(BaseModel):
    """Request to store encrypted session keys for participants"""
    conversation_id: str
    keys: List[dict]  # [{"user_id": "...", "encrypted_session_key": "..."}, ...]


class GetKeyResponse(BaseModel):
    """Response containing encrypted session key"""
    conversation_id: str
    user_id: str
    encrypted_session_key: str


def get_key_repo(db = Depends(mongo_db_dependency)) -> ConversationKeyRepository:
    return ConversationKeyRepository(db)


@router.post("/store", status_code=status.HTTP_201_CREATED)
async def store_conversation_keys(
    payload: StoreKeyRequest,
    current_user: dict = Depends(get_current_user),
    repo: ConversationKeyRepository = Depends(get_key_repo)
):
    """
    Store encrypted session keys for all participants in a conversation.
    This is called when initiating an encrypted conversation.
    
    **IMPORTANT**: Only overwrites keys for the current user.
    For other users, only stores if key doesn't exist (to prevent overwriting peer's keys).
    """
    if not payload.keys:
        raise HTTPException(status_code=400, detail="No keys provided")
    
    current_user_id = current_user["_id"]
    stored_count = 0
    skipped_count = 0
    
    for key_data in payload.keys:
        user_id = key_data.get("user_id")
        encrypted_key = key_data.get("encrypted_session_key")
        
        if not user_id or not encrypted_key:
            continue
        
        # Check if key already exists
        existing_key = await repo.get_key(payload.conversation_id, user_id)
        
        if existing_key is not None and user_id != current_user_id:
            # Key exists for another user - don't overwrite (they uploaded their own key)
            skipped_count += 1
            continue
        
        # Store key (either new or overwriting own key)
        await repo.store_key(payload.conversation_id, user_id, encrypted_key)
        stored_count += 1
    
    return {
        "message": f"Stored {stored_count} keys, skipped {skipped_count} existing keys",
        "conversation_id": payload.conversation_id
    }


@router.get("/{conversation_id}/my-key", response_model=GetKeyResponse)
async def get_my_conversation_key(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    repo: ConversationKeyRepository = Depends(get_key_repo)
):
    """
    Get the encrypted session key for the current user in a specific conversation.
    The client will decrypt this with their private RSA key to get the AES session key.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = current_user["_id"]
    logger.info(f"[KEY_FETCH] User {user_id} fetching key for conversation {conversation_id}")
    
    key_doc = await repo.get_key(conversation_id, user_id)
    
    if not key_doc:
        logger.warning(f"[KEY_FETCH] ❌ Key NOT FOUND for user {user_id} in conversation {conversation_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session key not found for this conversation"
        )
    
    logger.info(f"[KEY_FETCH] ✅ Key FOUND for user {user_id}, encrypted key length: {len(key_doc['encrypted_session_key'])}")
    
    return GetKeyResponse(
        conversation_id=key_doc["conversation_id"],
        user_id=key_doc["user_id"],
        encrypted_session_key=key_doc["encrypted_session_key"]
    )


@router.get("/{conversation_id}/all-keys")
async def get_all_conversation_keys(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    repo: ConversationKeyRepository = Depends(get_key_repo)
):
    """
    Get all encrypted session keys for a conversation.
    This can be used to verify all participants have keys or for debugging.
    """
    keys = await repo.get_keys_for_conversation(conversation_id)
    return {"items": keys}


@router.delete("/{conversation_id}/my-key")
async def delete_my_conversation_key(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    repo: ConversationKeyRepository = Depends(get_key_repo)
):
    """
    Delete the encrypted session key for the current user in a conversation.
    This is useful when the key cannot be decrypted (e.g., after key rotation)
    and needs to be recreated.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = current_user["_id"]
    logger.info(f"[KEY_DELETE] User {user_id} deleting their key for conversation {conversation_id}")
    
    # Delete only the current user's key
    result = await repo.collection.delete_one({
        "conversation_id": conversation_id,
        "user_id": user_id
    })
    
    if result.deleted_count == 0:
        logger.warning(f"[KEY_DELETE] No key found to delete for user {user_id} in conversation {conversation_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session key not found"
        )
    
    logger.info(f"[KEY_DELETE] ✅ Successfully deleted key for user {user_id} in conversation {conversation_id}")
    return {"message": "Key deleted successfully"}

