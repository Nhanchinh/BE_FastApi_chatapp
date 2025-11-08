from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database.connection import mongo_db_dependency
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.services.chat_service import ChatService
from app.utils.dependencies import get_current_user


router = APIRouter(prefix="/conversations", tags=["chat"])


def get_chat_service(db = Depends(mongo_db_dependency)) -> ChatService:
    convo_repo = ConversationRepository(db)
    msg_repo = MessageRepository(db)
    return ChatService(msg_repo, convo_repo)


@router.get("")
async def list_conversations(limit: int = Query(20, ge=1, le=100), cursor: Optional[str] = None, current_user: dict = Depends(get_current_user), service: ChatService = Depends(get_chat_service)):
    items, next_cursor = await service.list_conversations(current_user["_id"], limit=limit, cursor=cursor)
    return {"items": items, "next_cursor": next_cursor}


@router.get("/{conversation_id}/messages")
async def list_messages(conversation_id: str, limit: int = Query(50, ge=1, le=200), cursor: Optional[str] = None, current_user: dict = Depends(get_current_user), service: ChatService = Depends(get_chat_service)):
    messages, next_cursor = await service.get_history(conversation_id, limit=limit, cursor=cursor)
    return {"items": messages, "next_cursor": next_cursor}


@router.delete("/{conversation_id}", status_code=status.HTTP_200_OK)
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service)
):
    """
    Xóa cuộc trò chuyện.
    """
    try:
        deleted = await service.delete_conversation(conversation_id, current_user["_id"])
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


