from typing import Literal, Optional, TypedDict


PushPlatform = Literal["fcm", "webpush"]


class DeviceDocument(TypedDict, total=False):
    _id: str
    user_id: str
    platform: PushPlatform
    token: str
    last_seen_at: str


