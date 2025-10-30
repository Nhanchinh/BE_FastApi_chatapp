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
async def send_friend_request(target_user_id: str, current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service)):
    requester_id = current_user["_id"]
    if requester_id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot befriend yourself.")
    ok = await service.send_friend_request(requester_id, target_user_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Friend request already sent.")
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
async def friend_list(current_user: dict = Depends(get_current_user), service: FriendService = Depends(get_friend_service)):
    friends = await service.get_friend_list(current_user["_id"])
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
