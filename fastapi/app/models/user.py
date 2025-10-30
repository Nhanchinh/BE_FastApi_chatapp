from typing import Literal, Optional, TypedDict


UserRole = Literal["admin", "user"]


class UserDocument(TypedDict, total=False):

    _id: str
    email: str
    hashed_password: str
    full_name: Optional[str]
    role: UserRole


