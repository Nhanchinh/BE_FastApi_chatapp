from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.database.connection import mongo_db_dependency
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.conversation_key_repository import ConversationKeyRepository
from app.services.chat_service import ChatService
from app.utils.dependencies import get_current_user
from app.repositories.user_repository import UserRepository


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


class CreateGroupRequest(BaseModel):
    name: str
    member_ids: List[str]
    keys: List[EncryptedKeyDto]


class CreateGroupResponse(BaseModel):
    conversation_id: str
    participants: List[str]
    name: str
    group_key_version: int
    owner_id: str


class AddMembersRequest(BaseModel):
    member_ids: List[str]
    keys: List[EncryptedKeyDto]


class MemberDto(BaseModel):
    user_id: str
    full_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None


class GroupInfoResponse(BaseModel):
    conversation_id: str
    name: str | None = None
    participants: List[MemberDto]
    owner_id: str
    group_key_version: int


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


@router.post("/groups", status_code=status.HTTP_201_CREATED, response_model=CreateGroupResponse)
async def create_group(
    payload: CreateGroupRequest,
    current_user: dict = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
    key_repo: ConversationKeyRepository = Depends(get_key_repo),
    convo_repo: ConversationRepository = Depends(lambda db=Depends(mongo_db_dependency): ConversationRepository(db)),
):
    if not payload.member_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Members required")
    # Ensure creator is in members
    members = list(set(payload.member_ids + [current_user["_id"]]))
    # Create group conversation
    convo = await convo_repo.create_group(payload.name, members, owner_id=current_user["_id"])
    # Store encrypted keys (groupKey encrypted for each member)
    try:
        for key in payload.keys:
            await key_repo.store_key(convo["_id"], key.user_id, key.encrypted_session_key, version=1)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error storing keys: {str(e)}")
    return CreateGroupResponse(
        conversation_id=convo["_id"],
        participants=members,
        name=convo.get("name", ""),
        group_key_version=convo.get("group_key_version", 1),
        owner_id=convo.get("owner_id", current_user["_id"]),
    )


@router.post("/groups/{conversation_id}/members", response_model=GroupInfoResponse)
async def add_members(
    conversation_id: str,
    payload: AddMembersRequest,
    current_user: dict = Depends(get_current_user),
    convo_repo: ConversationRepository = Depends(lambda db=Depends(mongo_db_dependency): ConversationRepository(db)),
    key_repo: ConversationKeyRepository = Depends(get_key_repo),
    user_repo: UserRepository = Depends(lambda db=Depends(mongo_db_dependency): UserRepository(db)),
):
    convo = await convo_repo.get_by_id(conversation_id)
    if not convo or not convo.get("is_group"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    if convo.get("owner_id") != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner can add members")
    from bson import ObjectId
    try:
        convo_oid = ObjectId(conversation_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid conversation id")

    new_members = [uid for uid in payload.member_ids if uid not in convo.get("participants", [])]
    if not new_members:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No new members to add")
    # Update participants
    updated = await convo_repo.add_members(convo_oid, new_members)
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add members")
    # Store keys version stays the same
    version = convo.get("group_key_version", 1)
    try:
        for key in payload.keys:
            await key_repo.store_key(conversation_id, key.user_id, key.encrypted_session_key, version=version)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error storing keys: {str(e)}")

    # Build response members info
    participants = updated.get("participants", [])
    # Convert string IDs to ObjectId for MongoDB query
    try:
        participants_oid = [ObjectId(p) if isinstance(p, str) else p for p in participants]
    except Exception:
        participants_oid = []
    member_docs = await user_repo.collection.find({"_id": {"$in": participants_oid}}).to_list(length=500)
    members = []
    for m in member_docs:
        members.append(MemberDto(user_id=str(m["_id"]), full_name=m.get("full_name"), email=m.get("email"), avatar_url=m.get("avatar")))
    return GroupInfoResponse(
        conversation_id=conversation_id,
        name=updated.get("name"),
        participants=members,
        owner_id=updated.get("owner_id", current_user["_id"]),
        group_key_version=updated.get("group_key_version", version),
    )


@router.delete("/groups/{conversation_id}/members/{member_id}", response_model=GroupInfoResponse)
async def remove_member(
    conversation_id: str,
    member_id: str,
    current_user: dict = Depends(get_current_user),
    convo_repo: ConversationRepository = Depends(lambda db=Depends(mongo_db_dependency): ConversationRepository(db)),
    key_repo: ConversationKeyRepository = Depends(get_key_repo),
    user_repo: UserRepository = Depends(lambda db=Depends(mongo_db_dependency): UserRepository(db)),
):
    convo = await convo_repo.get_by_id(conversation_id)
    if not convo or not convo.get("is_group"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    if convo.get("owner_id") != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner can remove members")
    if member_id == current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Owner cannot remove self (use leave)")
    from bson import ObjectId
    try:
        convo_oid = ObjectId(conversation_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid conversation id")

    # Remove member
    ok = await convo_repo.remove_member(convo_oid, member_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Remove member failed")

    # Rekey: new version
    new_version = (convo.get("group_key_version") or 1) + 1
    await convo_repo.collection.update_one({"_id": convo_oid}, {"$set": {"group_key_version": new_version}})
    await key_repo.collection.delete_many({"conversation_id": conversation_id, "user_id": member_id})

    updated = await convo_repo.get_by_id(conversation_id)
    participants = updated.get("participants", [])
    # Convert string IDs to ObjectId for MongoDB query
    try:
        participants_oid = [ObjectId(p) if isinstance(p, str) else p for p in participants]
    except Exception:
        participants_oid = []
    member_docs = await user_repo.collection.find({"_id": {"$in": participants_oid}}).to_list(length=500)
    members = []
    for m in member_docs:
        members.append(MemberDto(user_id=str(m["_id"]), full_name=m.get("full_name"), email=m.get("email"), avatar_url=m.get("avatar")))
    return GroupInfoResponse(
        conversation_id=conversation_id,
        name=updated.get("name"),
        participants=members,
        owner_id=updated.get("owner_id", current_user["_id"]),
        group_key_version=updated.get("group_key_version", new_version),
    )


@router.post("/groups/{conversation_id}/leave", response_model=GroupInfoResponse)
async def leave_group(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    convo_repo: ConversationRepository = Depends(lambda db=Depends(mongo_db_dependency): ConversationRepository(db)),
    key_repo: ConversationKeyRepository = Depends(get_key_repo),
    user_repo: UserRepository = Depends(lambda db=Depends(mongo_db_dependency): UserRepository(db)),
):
    convo = await convo_repo.get_by_id(conversation_id)
    if not convo or not convo.get("is_group"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    from bson import ObjectId
    try:
        convo_oid = ObjectId(conversation_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid conversation id")

    participants = convo.get("participants", [])
    if current_user["_id"] not in participants:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant")

    # Handle owner leaving: transfer ownership
    new_owner = convo.get("owner_id")
    if convo.get("owner_id") == current_user["_id"]:
        remaining = [p for p in participants if p != current_user["_id"]]
        if remaining:
            new_owner = remaining[-1]
        else:
            await convo_repo.collection.delete_one({"_id": convo_oid})
            await key_repo.delete_keys_for_conversation(conversation_id)
            return GroupInfoResponse(conversation_id=conversation_id, name=convo.get("name"), participants=[], owner_id=current_user["_id"], group_key_version=convo.get("group_key_version", 1))

    await convo_repo.remove_member(convo_oid, current_user["_id"])
    await convo_repo.set_owner(convo_oid, new_owner)
    new_version = (convo.get("group_key_version") or 1) + 1
    await convo_repo.collection.update_one({"_id": convo_oid}, {"$set": {"group_key_version": new_version}})
    await key_repo.collection.delete_many({"conversation_id": conversation_id, "user_id": current_user["_id"]})

    updated = await convo_repo.get_by_id(conversation_id)
    participants = updated.get("participants", [])
    # Convert string IDs to ObjectId for MongoDB query
    try:
        participants_oid = [ObjectId(p) if isinstance(p, str) else p for p in participants]
    except Exception:
        participants_oid = []
    member_docs = await user_repo.collection.find({"_id": {"$in": participants_oid}}).to_list(length=500)
    members = []
    for m in member_docs:
        members.append(MemberDto(user_id=str(m["_id"]), full_name=m.get("full_name"), email=m.get("email"), avatar_url=m.get("avatar")))
    return GroupInfoResponse(
        conversation_id=conversation_id,
        name=updated.get("name"),
        participants=members,
        owner_id=updated.get("owner_id", new_owner),
        group_key_version=updated.get("group_key_version", new_version),
    )


@router.get("/groups/{conversation_id}", response_model=GroupInfoResponse)
async def get_group_info(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    convo_repo: ConversationRepository = Depends(lambda db=Depends(mongo_db_dependency): ConversationRepository(db)),
    user_repo: UserRepository = Depends(lambda db=Depends(mongo_db_dependency): UserRepository(db)),
):
    from bson import ObjectId
    convo = await convo_repo.get_by_id(conversation_id)
    if not convo or not convo.get("is_group"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    if current_user["_id"] not in convo.get("participants", []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant")
    participants = convo.get("participants", [])
    # Convert string IDs to ObjectId for MongoDB query
    try:
        participants_oid = [ObjectId(p) if isinstance(p, str) else p for p in participants]
    except Exception:
        participants_oid = []
    member_docs = await user_repo.collection.find({"_id": {"$in": participants_oid}}).to_list(length=500)
    members = []
    for m in member_docs:
        members.append(MemberDto(user_id=str(m["_id"]), full_name=m.get("full_name"), email=m.get("email"), avatar_url=m.get("avatar")))
    return GroupInfoResponse(
        conversation_id=conversation_id,
        name=convo.get("name"),
        participants=members,
        owner_id=convo.get("owner_id"),
        group_key_version=convo.get("group_key_version", 1),
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


