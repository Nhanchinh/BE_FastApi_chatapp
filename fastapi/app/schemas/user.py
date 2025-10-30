from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):

    email: EmailStr


class UserCreate(UserBase):

    password: str = Field(min_length=6)
    full_name: Optional[str] = None


class UserInDB(UserBase):

    id: str
    full_name: Optional[str] = None


class UserPublic(UserBase):

    id: str
    full_name: Optional[str] = None


class Token(BaseModel):

    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):

    sub: str
    exp: int


