from typing import Literal, Optional

class FriendRequestDocument(TypedDict, total=False):
    _id: str
    from_user: str
    to_user: str
    status: Literal["pending", "accepted", "rejected"]
    created_at: str
