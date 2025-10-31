from typing import List, Optional, TypedDict


class ConversationDocument(TypedDict, total=False):
    _id: str
    participants: List[str]
    last_message_at: str
    last_message_preview: Optional[str]
    # per-user unread counters (user_id -> count)
    unread_counters: dict[str, int]


