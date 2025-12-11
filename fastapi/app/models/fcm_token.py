from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class FCMTokenDocument(BaseModel):
    """FCM Token document stored in MongoDB"""
    user_id: str
    fcm_token: str
    device_id: Optional[str] = None  # Optional: to identify specific device
    device_type: str = "android"  # android, ios, web
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True  # Can be set to False when user logs out

class FCMTokenRequest(BaseModel):
    """Request body for storing FCM token"""
    fcm_token: str
    device_id: Optional[str] = None
    device_type: str = "android"

class FCMTokenResponse(BaseModel):
    """Response after storing FCM token"""
    success: bool
    message: str


