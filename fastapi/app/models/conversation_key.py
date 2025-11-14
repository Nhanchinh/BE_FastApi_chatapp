from typing import TypedDict


class ConversationKeyDocument(TypedDict, total=False):
    """
    Stores encrypted session keys for each user in a conversation.
    The session key is encrypted with the user's RSA public key.
    """
    _id: str
    conversation_id: str
    user_id: str
    encrypted_session_key: str  # AES session key encrypted with user's RSA public key (Base64)
    created_at: str  # ISO format timestamp

