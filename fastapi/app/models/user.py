from typing import Literal, Optional, TypedDict


UserRole = Literal["admin", "user"]


class UserDocument(TypedDict, total=False):

    _id: str
    email: str
    hashed_password: str
    full_name: Optional[str]
    role: UserRole
    friends: list[str]
    pending_requests: list[str]
    location: Optional[str]  # Sống tại
    hometown: Optional[str]  # Đến từ
    birth_year: Optional[int]  # Năm sinh
    last_seen: Optional[str]  # ISO format timestamp when user was last seen
    public_key: Optional[str]  # RSA public key (Base64 encoded PEM format) for E2EE


