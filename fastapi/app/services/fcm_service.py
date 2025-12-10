import firebase_admin
from firebase_admin import credentials, messaging
import os
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class FCMService:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FCMService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not FCMService._initialized:
            self._initialize_firebase()
            FCMService._initialized = True

    def _initialize_firebase(self):
        """Initialize Firebase Admin SDK"""
        try:
            # Path to serviceAccountKey.json
            cred_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                'serviceAccountKey.json'
            )
            
            if not os.path.exists(cred_path):
                logger.error(f"serviceAccountKey.json not found at {cred_path}")
                return
            
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            logger.info("✅ Firebase Admin SDK initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Firebase Admin SDK: {e}")

    async def send_notification(
        self,
        fcm_token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        Send push notification to a single device
        
        Args:
            fcm_token: FCM registration token of the device
            title: Notification title
            body: Notification body text
            data: Additional data payload (optional)
        
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Build notification
            notification = messaging.Notification(
                title=title,
                body=body
            )
            
            # Build Android-specific config
            android_config = messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id='chat_messages',
                    sound='default',
                    priority='high'
                )
            )
            
            # Build message
            message = messaging.Message(
                notification=notification,
                data=data or {},
                token=fcm_token,
                android=android_config
            )
            
            # Send message
            response = messaging.send(message)
            logger.info(f"✅ Notification sent successfully: {response}")
            return True
            
        except messaging.UnregisteredError:
            logger.warning(f"⚠️ FCM token is invalid or unregistered: {fcm_token}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to send notification: {e}")
            return False

    async def send_multicast_notification(
        self,
        fcm_tokens: list[str],
        title: str,
        body: str,
        data: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Send push notification to multiple devices
        
        Args:
            fcm_tokens: List of FCM registration tokens
            title: Notification title
            body: Notification body text
            data: Additional data payload (optional)
        
        Returns:
            Dictionary with success_count, failure_count, and responses
        """
        try:
            if not fcm_tokens:
                return {"success_count": 0, "failure_count": 0, "responses": []}
            
            # Build notification
            notification = messaging.Notification(
                title=title,
                body=body
            )
            
            # Build Android-specific config
            android_config = messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id='chat_messages',
                    sound='default',
                    priority='high'
                )
            )
            
            # Build multicast message
            message = messaging.MulticastMessage(
                notification=notification,
                data=data or {},
                tokens=fcm_tokens,
                android=android_config
            )
            
            # Send multicast
            response = messaging.send_multicast(message)
            logger.info(
                f"✅ Multicast sent: {response.success_count} success, "
                f"{response.failure_count} failure"
            )
            
            return {
                "success_count": response.success_count,
                "failure_count": response.failure_count,
                "responses": [
                    {"success": r.success, "message_id": getattr(r, 'message_id', None)}
                    for r in response.responses
                ]
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to send multicast notification: {e}")
            return {"success_count": 0, "failure_count": len(fcm_tokens), "responses": []}

    async def send_chat_message_notification(
        self,
        fcm_token: str,
        sender_name: str,
        message_content: str,
        conversation_id: str,
        is_group: bool = False,
        group_name: Optional[str] = None,
        sender_id: Optional[str] = None,
        is_encrypted: bool = False
    ) -> bool:
        """
        Send notification for new chat message
        
        Args:
            fcm_token: FCM token of the recipient
            sender_name: Name of the message sender
            message_content: Message content (will be truncated if too long)
            conversation_id: ID of the conversation
            is_group: Whether this is a group chat
            group_name: Name of the group (if group chat)
            sender_id: ID of the sender (required for 1-1 chat navigation)
        
        Returns:
            True if sent successfully
        """
        # Truncate message if too long
        max_length = 100
        if len(message_content) > max_length:
            message_content = message_content[:max_length] + "..."

        # Build title and body
        if is_group and group_name:
            title = f"{sender_name} trong {group_name}"
        else:
            title = sender_name

        # For encrypted messages, show placeholder text instead of encrypted content
        if is_encrypted:
            body = "đã gửi tin nhắn cho bạn"
        else:
            body = message_content

        # Build data payload
        data = {
            "type": "chat_message",
            "conversation_id": conversation_id,
            "sender_name": sender_name,
            "is_group": str(is_group).lower(),
            "is_encrypted": str(is_encrypted).lower()
        }

        # Add sender_id - REQUIRED for 1-1 chat navigation, optional for group
        if sender_id:
            data["sender_id"] = sender_id
        elif not is_group:
            # For 1-1 chat, sender_id is required - log warning if missing
            logger.warning(f"⚠️ Missing sender_id for 1-1 chat notification (conversation_id={conversation_id})")

        if group_name:
            data["group_name"] = group_name

        return await self.send_notification(
            fcm_token=fcm_token,
            title=title,
            body=body,
            data=data
        )


# Singleton instance
fcm_service = FCMService()

