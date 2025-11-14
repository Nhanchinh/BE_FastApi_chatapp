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
    """
    if not payload.keys:
        raise HTTPException(status_code=400, detail="No keys provided")
    
    stored_count = 0
    for key_data in payload.keys:
        user_id = key_data.get("user_id")
        encrypted_key = key_data.get("encrypted_session_key")
        
        if not user_id or not encrypted_key:
            continue
        
        await repo.store_key(payload.conversation_id, user_id, encrypted_key)
        stored_count += 1
    
    return {"message": f"Stored {stored_count} keys", "conversation_id": payload.conversation_id}


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
    key_doc = await repo.get_key(conversation_id, current_user["_id"])
    
    if not key_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session key not found for this conversation"
        )
    
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

