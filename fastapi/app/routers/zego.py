import json
import time
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.utils.dependencies import get_current_user
from app.utils.zego_token import generate_zego_token, get_zego_config

router = APIRouter(prefix="/zego", tags=["Zego"])


class ZegoTokenRequest(BaseModel):
    room_id: Optional[str] = ""
    expiry_seconds: int = 3600


class ZegoTokenResponse(BaseModel):
    token: str
    app_id: int
    expire_at: int


@router.post("/token", response_model=ZegoTokenResponse)
async def get_zego_token(req: ZegoTokenRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    app_id_str, server_secret = get_zego_config()
    if not app_id_str or not server_secret:
        raise HTTPException(status_code=500, detail="Missing Zego config")
    try:
        app_id = int(app_id_str)
    except Exception:
        raise HTTPException(status_code=500, detail="ZEGO_APP_ID must be an integer")

    payload_dict = {
        "room_id": req.room_id or "",
        "privilege": {
            1: 1,  # login
            2: 1,  # publish
        },
        "stream_id_list": None,
    }
    payload_str = json.dumps(payload_dict)

    try:
        token = generate_zego_token(
            app_id=app_id,
            user_id=str(current_user["_id"]),
            server_secret=server_secret,
            effective_time_in_seconds=req.expiry_seconds,
            payload=payload_str,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token generation failed: {e}")

    expire_at = int(time.time()) + req.expiry_seconds
    return ZegoTokenResponse(token=token, app_id=app_id, expire_at=expire_at)

