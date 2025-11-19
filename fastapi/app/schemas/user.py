from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


UserRole = Literal["admin", "user"]


class UserBase(BaseModel):

    email: EmailStr


class UserCreate(UserBase):

    password: str = Field(min_length=6)
    full_name: Optional[str] = None
    public_key: Optional[str] = None  # RSA public key for E2EE


class UserInDB(UserBase):

    id: str
    full_name: Optional[str] = None
    role: UserRole = "user"


class UserPublic(UserBase):

    id: str
    full_name: Optional[str] = None
    role: UserRole = "user"
    friend_count: Optional[int] = None
    location: Optional[str] = None
    hometown: Optional[str] = None
    birth_year: Optional[int] = None
    public_key: Optional[str] = None  # RSA public key for E2EE


class Token(BaseModel):

    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):

    sub: str
    exp: int


class UserProfileUpdate(BaseModel):
    """Schema để update profile user"""
    full_name: Optional[str] = None
    location: Optional[str] = None
    hometown: Optional[str] = None
    birth_year: Optional[int] = Field(None, ge=1900, le=2024)
    public_key: Optional[str] = None  # Allow updating public key


class LoginResponse(BaseModel):

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: UserPublic
    requires_public_key: bool = False


class RefreshTokenRequest(BaseModel):

    refresh_token: str = Field(..., min_length=10)


class RefreshTokenResponse(BaseModel):

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


