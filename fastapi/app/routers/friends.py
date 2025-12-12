from fastapi import APIRouter, Depends, HTTPException, status
from app.database.connection import mongo_db_dependency
from app.repositories.friend_repository import FriendRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.repositories.fcm_token_repository import FCMTokenRepository
from app.services.friend_service import FriendService
from app.services.fcm_service import FCMService
from app.utils.dependencies import get_current_user


def _display_name(user: dict | None) -> str:
    """Prefer full_name, fallback to email or generic label."""
    if not user:
        return "Người dùng"
    return user.get("full_name") or user.get("email") or "Người dùng"

router = APIRouter(prefix="/friends", tags=["friend"])

def get_friend_service(db = Depends(mongo_db_dependency)):
    friend_repo = FriendRepository(db)
    user_repo = UserRepository(db)
    return FriendService(friend_repo, user_repo)

@router.post("/request/{target_user_id}")
async def send_friend_request(target_user_id: str, current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service), db = Depends(mongo_db_dependency)):
    requester_id = current_user["_id"]
    if requester_id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot befriend yourself.")
    
    # Check if already friends - use friend_repo directly
    friend_repo = FriendRepository(db)
    if await friend_repo.is_friend(requester_id, target_user_id):
        raise HTTPException(status_code=400, detail="Already friends.")
    
    ok = await service.send_friend_request(requester_id, target_user_id)
    if not ok:
        # Check if there's a pending request from us
        request = await friend_repo.get_friend_request(requester_id, target_user_id)
        if request and request.get("status") == "pending":
            raise HTTPException(status_code=400, detail="Friend request already sent.")
        
        # Check if reverse request exists (other person sent to us)
        reverse_request = await friend_repo.get_friend_request(target_user_id, requester_id)
        if reverse_request and reverse_request.get("status") == "pending":
            raise HTTPException(status_code=400, detail="Friend request already received from this user. Please accept it instead.")
        
        # This shouldn't happen, but just in case
        raise HTTPException(status_code=400, detail="Unable to send friend request.")
    
    # Push notification to receiver
    try:
        user_repo = UserRepository(db)
        notif_repo = NotificationRepository(db)
        fcm_repo = FCMTokenRepository(db)
        requester = await user_repo.get_user_by_id(requester_id)
        receiver = await user_repo.get_user_by_id(target_user_id)
        sender_name = _display_name(requester)
        title = "Lời mời kết bạn"
        body = f"{sender_name} đã gửi cho bạn lời mời kết bạn"
        data = {"type": "friend_request", "from_user_id": requester_id}
        await notif_repo.create_notification(
            user_id=target_user_id,
            title=title,
            body=body,
            notif_type="friend_request",
            from_user_id=requester_id,
            from_user_name=sender_name,
            data=data,
        )
        tokens = await fcm_repo.get_user_tokens(target_user_id)
        if tokens:
            fcm_service = FCMService()
            payload = {k: str(v) for k, v in data.items()}
            for token in tokens:
                try:
                    await fcm_service.send_notification(token, title, body, payload)
                except Exception:
                    pass
    except Exception:
        # Notification failures should not block the main flow
        pass

    return {"msg": "Request sent"}

@router.post("/accept/{from_user_id}")
async def accept_friend_request(from_user_id: str, current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service), db = Depends(mongo_db_dependency)):
    ok = await service.accept_friend_request(from_user_id, current_user["_id"])
    if not ok:
        raise HTTPException(status_code=400, detail="No pending request to accept.")
    
    # Notify the original requester that their invite was accepted
    try:
        user_repo = UserRepository(db)
        notif_repo = NotificationRepository(db)
        fcm_repo = FCMTokenRepository(db)
        accepter = await user_repo.get_user_by_id(current_user["_id"])
        requester = await user_repo.get_user_by_id(from_user_id)
        accepter_name = _display_name(accepter)
        
        # Xóa notification friend_request cũ của người accept
        await notif_repo.delete_notifications_by_type_and_from_user(
            user_id=current_user["_id"],
            notif_type="friend_request",
            from_user_id=from_user_id
        )
        
        # Tạo notification mới cho người gửi request
        title = "Kết bạn thành công"
        body = f"{accepter_name} đã chấp nhận lời mời kết bạn"
        data = {"type": "friend_accept", "from_user_id": current_user["_id"]}
        await notif_repo.create_notification(
            user_id=from_user_id,
            title=title,
            body=body,
            notif_type="friend_accept",
            from_user_id=current_user["_id"],
            from_user_name=accepter_name,
            data=data,
        )
        tokens = await fcm_repo.get_user_tokens(from_user_id)
        if tokens:
            fcm_service = FCMService()
            payload = {k: str(v) for k, v in data.items()}
            for token in tokens:
                try:
                    await fcm_service.send_notification(token, title, body, payload)
                except Exception:
                    pass
    except Exception:
        pass

    return {"msg": "Friend added"}

@router.delete("/request/{user_id}")
async def cancel_friend_request(user_id: str, current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service), db = Depends(mongo_db_dependency)):
    ok = await service.cancel_friend_request(current_user["_id"], user_id)
    direction = "sent" if ok else None
    if not ok:
        ok = await service.cancel_friend_request(user_id, current_user["_id"])
        if ok:
            direction = "received"
    if not ok:
        raise HTTPException(status_code=404, detail="No such request.")

    # Notify the other user that the request was cancelled/rejected
    try:
        user_repo = UserRepository(db)
        notif_repo = NotificationRepository(db)
        fcm_repo = FCMTokenRepository(db)
        actor = await user_repo.get_user_by_id(current_user["_id"])
        actor_name = _display_name(actor)
        target_user_id = user_id
        
        # Xóa notification friend_request cũ
        if direction == "sent":
            # Người gửi hủy -> xóa notification của người nhận
            await notif_repo.delete_notifications_by_type_and_from_user(
                user_id=target_user_id,
                notif_type="friend_request",
                from_user_id=current_user["_id"]
            )
            title = "Lời mời kết bạn bị hủy"
            body = f"{actor_name} đã hủy lời mời kết bạn"
            notif_type = "friend_request_cancel"
        else:
            # Người nhận từ chối -> xóa notification của chính họ
            await notif_repo.delete_notifications_by_type_and_from_user(
                user_id=current_user["_id"],
                notif_type="friend_request",
                from_user_id=target_user_id
            )
            title = "Lời mời kết bạn bị từ chối"
            body = f"{actor_name} đã từ chối lời mời kết bạn"
            notif_type = "friend_request_reject"
        
        data = {"type": notif_type, "from_user_id": current_user["_id"]}
        await notif_repo.create_notification(
            user_id=target_user_id,
            title=title,
            body=body,
            notif_type=notif_type,
            from_user_id=current_user["_id"],
            from_user_name=actor_name,
            data=data,
        )
        tokens = await fcm_repo.get_user_tokens(target_user_id)
        if tokens:
            fcm_service = FCMService()
            payload = {k: str(v) for k, v in data.items()}
            for token in tokens:
                try:
                    await fcm_service.send_notification(token, title, body, payload)
                except Exception:
                    pass
    except Exception:
        pass

    return {"msg": "Request cancelled"}

@router.get("/list")
async def friend_list(current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service), db = Depends(mongo_db_dependency)):
    friends = await service.get_friend_list(current_user["_id"])
    
    # Add presence data (online status and last_seen) to friends
    if friends:
        from app.utils.realtime_bus import get_bus
        from app.repositories.user_repository import UserRepository
        
        bus = await get_bus()
        user_repo = UserRepository(db)
        friend_ids = [f.get("id") for f in friends if f.get("id")]
        
        # Get online status from Redis
        online_statuses = {}
        if getattr(bus, "enabled", False):
            try:
                import redis.asyncio as redis  # type: ignore
                r = bus._redis  # type: ignore
                for friend_id in friend_ids:
                    try:
                        ttl = await r.ttl(f"presence:{friend_id}")
                        online_statuses[friend_id] = ttl and ttl > 0
                    except Exception:
                        online_statuses[friend_id] = False
            except Exception:
                pass
        
        # Get last_seen from MongoDB
        users = await user_repo.get_users_by_ids(friend_ids)
        user_last_seen = {user["_id"]: user.get("last_seen") for user in users if user.get("last_seen")}
        
        # Add presence data to friends
        for friend in friends:
            friend_id = friend.get("id")
            if friend_id:
                friend["is_online"] = online_statuses.get(friend_id, False)
                friend["last_seen"] = user_last_seen.get(friend_id)
    
    return {"friends": friends}

@router.get("/requests")
async def received_friend_requests(current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service)):
    requests = await service.get_received_requests(current_user["_id"])
    return {"requests": requests}

@router.delete("/{friend_id}")
async def unfriend(friend_id: str, current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service)):
    if friend_id == current_user["_id"]:
        raise HTTPException(status_code=400, detail="Cannot unfriend yourself.")
    ok = await service.unfriend(current_user["_id"], friend_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Friend relation not found.")

    # Notify the other user about unfriend action
    try:
        db = service.friend_repo._user_collection.database  # reuse db from repo
        user_repo = UserRepository(db)
        notif_repo = NotificationRepository(db)
        fcm_repo = FCMTokenRepository(db)
        actor = await user_repo.get_user_by_id(current_user["_id"])
        actor_name = _display_name(actor)
        title = "Bị hủy kết bạn"
        body = f"{actor_name} đã hủy kết bạn với bạn"
        data = {"type": "unfriend", "from_user_id": current_user["_id"]}
        await notif_repo.create_notification(
            user_id=friend_id,
            title=title,
            body=body,
            notif_type="unfriend",
            from_user_id=current_user["_id"],
            from_user_name=actor_name,
            data=data,
        )
        tokens = await fcm_repo.get_user_tokens(friend_id)
        if tokens:
            fcm_service = FCMService()
            payload = {k: str(v) for k, v in data.items()}
            for token in tokens:
                try:
                    await fcm_service.send_notification(token, title, body, payload)
                except Exception:
                    pass
    except Exception:
        pass

    return {"msg": "Unfriended"}

@router.get("/{friend_id}")
async def get_friend_detail(friend_id: str, current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service)):
    friend = await service.get_friend_by_id(current_user["_id"], friend_id)
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found or not in your friend list.")
    return friend