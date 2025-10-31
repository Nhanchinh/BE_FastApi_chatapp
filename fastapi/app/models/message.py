from typing import Optional, TypedDict


class MessageDocument(TypedDict, total=False):
    _id: str
    conversation_id: str
    sender_id: str
    receiver_id: str
    content: str
    timestamp: str
    # delivery states
    delivered: bool
    seen: bool
    # client ack
    client_message_id: Optional[str]


