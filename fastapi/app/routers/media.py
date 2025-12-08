import base64
import os
from pathlib import Path
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database.connection import mongo_db_dependency
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.media_repository import MediaRepository
from app.utils.dependencies import get_current_user


router = APIRouter(prefix="/media", tags=["media"])
MAX_MEDIA_SIZE = 5 * 1024 * 1024  # 5 MB for images and files
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB for videos
MEDIA_STORAGE_PATH = Path(os.getenv("MEDIA_STORAGE_PATH", "media_uploads")).resolve()
MEDIA_STORAGE_PATH.mkdir(parents=True, exist_ok=True)


def get_media_repo(db = Depends(mongo_db_dependency)) -> MediaRepository:
    return MediaRepository(db, MEDIA_STORAGE_PATH)


def get_conversation_repo(db = Depends(mongo_db_dependency)) -> ConversationRepository:
    return ConversationRepository(db)


class MediaUploadRequest(BaseModel):
    conversation_id: str
    media_data: str  # Base64 encoded encrypted bytes
    iv: str
    mime_type: str = Field(..., max_length=128)
    size: int = Field(..., ge=1)


class MediaUploadResponse(BaseModel):
    media_id: str


class MediaDownloadResponse(BaseModel):
    media_id: str
    conversation_id: str
    mime_type: str
    size: int
    iv: str
    media_data: str  # Base64 encoded encrypted bytes


async def _ensure_participant(conversation_repo: ConversationRepository, conversation_id: str, user_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(conversation_id)
    except Exception:
        return None
    conversation = await conversation_repo.collection.find_one({"_id": oid})
    if not conversation:
        return None
    participants = conversation.get("participants", [])
    if user_id not in participants:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a participant of this conversation")
    conversation["_id"] = str(conversation["_id"])
    return conversation


@router.post("", response_model=MediaUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    payload: MediaUploadRequest,
    current_user: dict = Depends(get_current_user),
    media_repo: MediaRepository = Depends(get_media_repo),
    conversation_repo: ConversationRepository = Depends(get_conversation_repo),
):
    conversation = await _ensure_participant(conversation_repo, payload.conversation_id, current_user["_id"])
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Check size limit based on media type
    max_size = MAX_VIDEO_SIZE if payload.mime_type.startswith("video/") else MAX_MEDIA_SIZE
    if payload.size > max_size:
        max_size_mb = max_size / (1024 * 1024)
        file_size_mb = payload.size / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Media file too large. Maximum size: {max_size_mb:.0f}MB, file size: {file_size_mb:.1f}MB"
        )

    try:
        data_bytes = base64.b64decode(payload.media_data)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid media data")

    media_id = await media_repo.save_media(
        conversation_id=payload.conversation_id,
        uploader_id=current_user["_id"],
        data=data_bytes,
        iv=payload.iv,
        mime_type=payload.mime_type,
        size=payload.size,
    )
    return MediaUploadResponse(media_id=media_id)


@router.get("/{media_id}", response_model=MediaDownloadResponse)
async def download_media(
    media_id: str,
    current_user: dict = Depends(get_current_user),
    media_repo: MediaRepository = Depends(get_media_repo),
    conversation_repo: ConversationRepository = Depends(get_conversation_repo),
):
    media_doc = await media_repo.get_media(media_id)
    if not media_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    conversation = await _ensure_participant(conversation_repo, media_doc["conversation_id"], current_user["_id"])
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    file_path = media_doc.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file missing")

    data_bytes: bytes = Path(file_path).read_bytes()
    encoded = base64.b64encode(data_bytes).decode("utf-8")
    return MediaDownloadResponse(
        media_id=media_doc["_id"],
        conversation_id=media_doc["conversation_id"],
        mime_type=media_doc.get("mime_type", "application/octet-stream"),
        size=media_doc.get("size", len(data_bytes)),
        iv=media_doc.get("iv"),
        media_data=encoded,
    )

