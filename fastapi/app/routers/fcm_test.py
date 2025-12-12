from fastapi import APIRouter, Depends
from app.services.fcm_service import fcm_service
from pydantic import BaseModel

router = APIRouter(prefix="/test", tags=["Test FCM"])

class TestNotificationRequest(BaseModel):
    fcm_token: str
    title: str
    body: str
    conversation_id: str = "test123"

@router.post("/send-notification")
async def send_test_notification(request: TestNotificationRequest):
    """
    Test endpoint để gửi notification thủ công
    Không cần authentication - chỉ để test
    """
    success, token_invalid = await fcm_service.send_chat_message_notification(
        fcm_token=request.fcm_token,
        sender_name=request.title,
        message_content=request.body,
        conversation_id=request.conversation_id,
        is_group=False
    )
    
    if success:
        return {
            "success": True,
            "message": "Notification sent successfully"
        }
    elif token_invalid:
        return {
            "success": False,
            "message": "Failed to send notification: FCM token is invalid or unregistered"
        }
    else:
        return {
            "success": False,
            "message": "Failed to send notification"
        }



