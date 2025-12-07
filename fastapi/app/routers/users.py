from fastapi import APIRouter, Depends, HTTPException, Query
from app.database.connection import mongo_db_dependency
from app.repositories.user_repository import UserRepository
from app.services.user_service import UserService
from app.utils.dependencies import get_current_user


router = APIRouter(prefix="/users", tags=["users"])


def get_user_service(db = Depends(mongo_db_dependency)):
    user_repo = UserRepository(db)
    return UserService(user_repo)


@router.get("/search")
async def search_users(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50), prefix: bool = Query(False), current_user: dict = Depends(get_current_user), service: UserService = Depends(get_user_service)):
    results = await service.search_users(query=q, limit=limit, exclude_user_id=current_user["_id"], prefix=prefix)
    return {"items": results}


@router.get("/public-keys/batch")
async def get_public_keys_batch(user_ids: str = Query(..., description="Comma-separated user IDs"), current_user: dict = Depends(get_current_user), db = Depends(mongo_db_dependency)):
    """
    Fetch public keys for multiple users at once.
    Query param: user_ids (comma-separated, e.g., "id1,id2,id3")
    Returns: {"items": [{"user_id": "...", "public_key": "..."}, ...]}
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_repo = UserRepository(db)
    ids_list = [uid.strip() for uid in user_ids.split(",") if uid.strip()]
    
    if not ids_list:
        raise HTTPException(status_code=400, detail="No user IDs provided")
    
    if len(ids_list) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 user IDs allowed per request")
    
    logger.info(f"[PUBLIC_KEYS] Fetching public keys for users: {ids_list}")
    users = await user_repo.get_users_by_ids(ids_list)
    
    results = []
    for user in users:
        user_id = user.get("_id")
        public_key = user.get("public_key")
        results.append({
            "user_id": user_id,
            "public_key": public_key,
            "full_name": user.get("full_name")  # Include name for reference
        })
        if public_key:
            logger.info(f"[PUBLIC_KEYS] User {user_id} ({user.get('full_name')}): public key length = {len(public_key)}")
        else:
            logger.warning(f"[PUBLIC_KEYS] ❌ User {user_id} ({user.get('full_name')}): NO PUBLIC KEY!")
    
    return {"items": results}


@router.get("/{user_id}")
async def get_user_by_id(user_id: str, current_user: dict = Depends(get_current_user), service: UserService = Depends(get_user_service), db = Depends(mongo_db_dependency)):
    """Get public user information by user ID. Requires authentication but can access any user's public info."""
    user_repo = UserRepository(db)
    user = await user_repo.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Return public information only
    from app.repositories.friend_repository import FriendRepository
    friend_repo = FriendRepository(db)
    try:
        friends = await friend_repo.list_friends(user_id)
        friend_count = len(friends)
    except Exception:
        friend_count = 0
    
    return {
        "id": user.get("_id"),
        "email": user.get("email"),
        "full_name": user.get("full_name"),
        "role": user.get("role", "user"),
        "friend_count": friend_count,
        "location": user.get("location"),
        "hometown": user.get("hometown"),
        "birth_year": user.get("birth_year"),
        "public_key": user.get("public_key"),
    }


