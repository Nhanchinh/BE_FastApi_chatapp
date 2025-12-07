from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.database.connection import mongo_db_dependency
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.conversation_key_repository import ConversationKeyRepository
from app.services.chat_service import ChatService
from app.utils.dependencies import get_current_user


router = APIRouter(prefix="/conversations", tags=["chat"])


class EncryptedKeyDto(BaseModel):
    """Encrypted session key for a participant"""
    user_id: str
    encrypted_session_key: str


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation with encryption keys"""
    participant_id: str
    keys: List[EncryptedKeyDto]  # Encrypted keys for all participants


class CreateConversationResponse(BaseModel):
    """Response after creating conversation"""
    conversation_id: str
    participants: List[str]


def get_chat_service(db = Depends(mongo_db_dependency)) -> ChatService:
    convo_repo = ConversationRepository(db)
    msg_repo = MessageRepository(db)
    return ChatService(msg_repo, convo_repo)


def get_key_repo(db = Depends(mongo_db_dependency)) -> ConversationKeyRepository:
    return ConversationKeyRepository(db)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CreateConversationResponse)
async def create_conversation(
    payload: CreateConversationRequest,
    current_user: dict = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
    key_repo: ConversationKeyRepository = Depends(get_key_repo)
):
    """
    Tạo conversation mới với encryption keys.
    Đảm bảo cả conversation và keys đều được lưu vào DB trước khi trả về conversation_id.
    
    Luồng:
    1. A -> Server: createConversation (với participant_id và encrypted keys)
    2. Server: tạo conversation + lưu encrypted keys
    3. Server: trả về conversationId (CHỈ KHI DB ĐÃ GHI XONG)
    4. A: Bắt đầu cho phép gửi tin nhắn
    """
    try:
        # Validate participant
        if payload.participant_id == current_user["_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create conversation with yourself"
            )
        
        # Convert keys to dict format
        encrypted_keys = [
            {"user_id": key.user_id, "encrypted_session_key": key.encrypted_session_key}
            for key in payload.keys
        ]
        
        # Tạo conversation và lưu keys đồng bộ
        result = await service.create_conversation_with_keys(
            current_user_id=current_user["_id"],
            participant_id=payload.participant_id,
            key_repo=key_repo,
            encrypted_keys=encrypted_keys
        )
        
        return CreateConversationResponse(
            conversation_id=result["conversation_id"],
            participants=result["participants"]
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating conversation: {str(e)}"
        )


@router.get("")
async def list_conversations(limit: int = Query(20, ge=1, le=100), cursor: Optional[str] = None, current_user: dict = Depends(get_current_user), service: ChatService = Depends(get_chat_service), db = Depends(mongo_db_dependency)):
    items, next_cursor = await service.list_conversations(current_user["_id"], limit=limit, cursor=cursor)
    
    # Convert datetime objects to ISO format strings
    from datetime import datetime, timezone
    for item in items:
        if "last_message_at" in item and isinstance(item["last_message_at"], datetime):
            dt = item["last_message_at"]
            # Đảm bảo datetime có timezone (UTC)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            item["last_message_at"] = dt.isoformat()
    
    # Add presence data (online status) to conversations
    if items:
        from app.utils.realtime_bus import get_bus
        bus = await get_bus()
        current_user_id = current_user["_id"]
        
        # Get online status for other participants in each conversation
        if getattr(bus, "enabled", False):
            try:
                import redis.asyncio as redis  # type: ignore
                r = bus._redis  # type: ignore
                for item in items:
                    participants = item.get("participants", [])
                    # Find the other participant (not current user)
                    other_participant = None
                    for p in participants:
                        if p != current_user_id:
                            other_participant = p
                            break
                    
                    if other_participant:
                        try:
                            ttl = await r.ttl(f"presence:{other_participant}")
                            item["is_online"] = ttl and ttl > 0
                        except Exception:
                            item["is_online"] = False
                    else:
                        item["is_online"] = False
            except Exception:
                # If Redis fails, set all to False
                for item in items:
                    item["is_online"] = False
        else:
            # No Redis, set all to False
            for item in items:
                item["is_online"] = False
    
    return {"items": items, "next_cursor": next_cursor}


@router.get("/{conversation_id}/messages")
async def list_messages(conversation_id: str, limit: int = Query(50, ge=1, le=200), cursor: Optional[str] = None, current_user: dict = Depends(get_current_user), service: ChatService = Depends(get_chat_service)):
    messages, next_cursor = await service.get_history(conversation_id, limit=limit, cursor=cursor)
    
    # Convert datetime objects to ISO format strings
    from datetime import datetime, timezone
    for message in messages:
        if "timestamp" in message and isinstance(message["timestamp"], datetime):
            dt = message["timestamp"]
            # Đảm bảo datetime có timezone (UTC)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            message["timestamp"] = dt.isoformat()
    
    return {"items": messages, "next_cursor": next_cursor}


@router.delete("/{conversation_id}", status_code=status.HTTP_200_OK)
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
    key_repo: ConversationKeyRepository = Depends(get_key_repo)
):
    """
    Xóa cuộc trò chuyện và tất cả conversation keys liên quan.
    """
    try:
        deleted = await service.delete_conversation(conversation_id, current_user["_id"], key_repo)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found or you don't have permission to delete it"
            )
        return {"msg": "Conversation deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting conversation: {str(e)}"
        )


