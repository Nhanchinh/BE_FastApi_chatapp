from fastapi import APIRouter, Depends

from app.database.connection import mongo_db_dependency
from app.repositories.device_repository import DeviceRepository
from app.utils.dependencies import get_current_user


router = APIRouter(prefix="/devices", tags=["push"])


@router.post("/register")
async def register_device(payload: dict, current_user: dict = Depends(get_current_user), db = Depends(mongo_db_dependency)):
    repo = DeviceRepository(db)
    platform = payload.get("platform")  # "fcm" | "webpush"
    token = payload.get("token")
    if not platform or not token:
        return {"ok": False, "error": "platform and token required"}
    doc = await repo.register(current_user["_id"], platform, token)
    return {"ok": True, "device": {"platform": doc["platform"], "token": doc["token"]}}


