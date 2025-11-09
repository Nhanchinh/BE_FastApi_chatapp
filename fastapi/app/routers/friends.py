from fastapi import APIRouter, Depends, HTTPException, status
from app.database.connection import mongo_db_dependency
from app.repositories.friend_repository import FriendRepository
from app.repositories.user_repository import UserRepository
from app.services.friend_service import FriendService
from app.utils.dependencies import get_current_user

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
    return {"msg": "Request sent"}

@router.post("/accept/{from_user_id}")
async def accept_friend_request(from_user_id: str, current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service)):
    ok = await service.accept_friend_request(from_user_id, current_user["_id"])
    if not ok:
        raise HTTPException(status_code=400, detail="No pending request to accept.")
    return {"msg": "Friend added"}

@router.delete("/request/{user_id}")
async def cancel_friend_request(user_id: str, current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service)):
    ok = await service.cancel_friend_request(current_user["_id"], user_id)
    if not ok:
        ok = await service.cancel_friend_request(user_id, current_user["_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="No such request.")
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
    return {"msg": "Unfriended"}

@router.get("/{friend_id}")
async def get_friend_detail(friend_id: str, current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service)):
    friend = await service.get_friend_by_id(current_user["_id"], friend_id)
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found or not in your friend list.")
    return friend