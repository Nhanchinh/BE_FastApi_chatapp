from fastapi import APIRouter
from app.utils.realtime_bus import get_bus


router = APIRouter(prefix="/presence", tags=["chat"])


@router.get("/{user_id}")
async def presence(user_id: str):
    """
    Trả về online status. Nếu có Redis, kiểm tra key presence; nếu không, trả về online=false (hoặc có thể mở rộng lấy từ WebSocket manager nếu cần).
    """
    bus = await get_bus()
    online = False
    last_seen = None
    if getattr(bus, "enabled", False):
        try:
            import redis.asyncio as redis  # type: ignore
            r = bus._redis  # type: ignore
            ttl = await r.ttl(f"presence:{user_id}")
            online = ttl and ttl > 0
        except Exception:
            online = False
    return {"user_id": user_id, "online": bool(online), "last_seen": last_seen}


