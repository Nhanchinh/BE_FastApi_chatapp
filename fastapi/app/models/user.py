from typing import Optional, TypedDict


class UserDocument(TypedDict, total=False):

    _id: str
    email: str
    hashed_password: str
    full_name: Optional[str]


