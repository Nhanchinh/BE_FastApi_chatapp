from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


UserRole = Literal["admin", "user"]


class UserBase(BaseModel):

    email: EmailStr


class UserCreate(UserBase):

    password: str = Field(min_length=6)
    full_name: Optional[str] = None


class UserInDB(UserBase):

    id: str
    full_name: Optional[str] = None
    role: UserRole = "user"


class UserPublic(UserBase):

    id: str
    full_name: Optional[str] = None
    role: UserRole = "user"


class Token(BaseModel):

    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):

    sub: str
    exp: int


