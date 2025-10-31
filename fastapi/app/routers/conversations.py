from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

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


