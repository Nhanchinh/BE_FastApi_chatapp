from fastapi import APIRouter, Query, Depends
from typing import List, Optional
from app.utils.realtime_bus import get_bus
from app.utils.dependencies import get_current_user
from app.database.connection import mongo_db_dependency
from app.repositories.user_repository import UserRepository
from datetime import datetime, timezone


router = APIRouter(prefix="/presence", tags=["chat"])


@router.get("/{user_id}")
async def presence(user_id: str, db = Depends(mongo_db_dependency)):
    """
    Trả về online status và last_seen cho một user.
    Nếu có Redis, kiểm tra key presence; nếu không, trả về online=false.
    Last_seen được lấy từ MongoDB user document.
    """
    bus = await get_bus()
    online = False
    last_seen = None
    
    # Check Redis for online status
    if getattr(bus, "enabled", False):
        try:
            import redis.asyncio as redis  # type: ignore
            r = bus._redis  # type: ignore
            ttl = await r.ttl(f"presence:{user_id}")
            online = ttl and ttl > 0
        except Exception:
            online = False
    
    # Get last_seen from MongoDB
    try:
        user_repo = UserRepository(db)
        user = await user_repo.get_user_by_id(user_id)
        if user and user.get("last_seen"):
            last_seen = user.get("last_seen")
    except Exception:
        pass
    
    return {"user_id": user_id, "online": bool(online), "last_seen": last_seen}


@router.get("/batch")
async def batch_presence(user_ids: str = Query(..., description="Comma-separated list of user IDs"), db = Depends(mongo_db_dependency)):
    """
    Trả về online status và last_seen cho nhiều users cùng lúc.
    Ví dụ: /presence/batch?user_ids=user1,user2,user3
    """
    bus = await get_bus()
    user_id_list = [uid.strip() for uid in user_ids.split(",") if uid.strip()]
    
    if not user_id_list:
        return {"presences": []}
    
    results = []
    
    # Get online status from Redis for all users
    online_statuses = {}
    if getattr(bus, "enabled", False):
        try:
            import redis.asyncio as redis  # type: ignore
            r = bus._redis  # type: ignore
            for user_id in user_id_list:
                try:
                    ttl = await r.ttl(f"presence:{user_id}")
                    online_statuses[user_id] = ttl and ttl > 0
                except Exception:
                    online_statuses[user_id] = False
        except Exception:
            pass
    
    # Get last_seen from MongoDB for all users
    try:
        user_repo = UserRepository(db)
        users = await user_repo.get_users_by_ids(user_id_list)
        user_last_seen = {user["_id"]: user.get("last_seen") for user in users if user.get("last_seen")}
        
        for user_id in user_id_list:
            results.append({
                "user_id": user_id,
                "online": online_statuses.get(user_id, False),
                "last_seen": user_last_seen.get(user_id)
            })
    except Exception:
        # Fallback: just return online status if MongoDB query fails
        for user_id in user_id_list:
            results.append({
                "user_id": user_id,
                "online": online_statuses.get(user_id, False),
                "last_seen": None
            })
    
    return {"presences": results}


@router.post("/offline")
async def set_offline(current_user: dict = Depends(get_current_user), db = Depends(mongo_db_dependency)):
    """
    Đánh dấu user hiện tại là offline (dùng khi logout).
    Xóa presence key trong Redis và update last_seen trong MongoDB.
    """
    user_id = current_user["_id"]
    bus = await get_bus()
    
    # Clear presence key trong Redis
    if getattr(bus, "enabled", False):
        try:
            await bus.clear_presence(user_id)
        except Exception:
            pass
    
    # Update last_seen trong MongoDB
    try:
        user_repo = UserRepository(db)
        await user_repo.update_last_seen(user_id)
    except Exception:
        pass
    
    return {"message": "User marked as offline", "user_id": user_id}


