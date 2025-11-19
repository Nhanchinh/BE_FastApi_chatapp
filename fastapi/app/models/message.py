from typing import Optional, TypedDict


class MessageDocument(TypedDict, total=False):
    _id: str
    conversation_id: str
    sender_id: str
    receiver_id: str
    content: str  # For E2EE: this contains the ciphertext (Base64)
    timestamp: str
    # delivery states
    delivered: bool
    seen: bool
    # client ack
    client_message_id: Optional[str]
    # E2EE fields
    iv: Optional[str]  # Initialization Vector for AES-GCM (Base64)
    is_encrypted: Optional[bool]  # Flag to indicate if message is encrypted
    # Media fields
    media_id: Optional[str]
    media_mime_type: Optional[str]
    media_size: Optional[int]


