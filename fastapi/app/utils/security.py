import os
from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext


_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "60"))
REFRESH_TOKEN_EXPIRES_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRES_DAYS", "7"))


def hash_password(password: str) -> str:

    return _pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:

    return _pwd_context.verify(password, hashed_password)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:

    if expires_delta is None:
        expires_delta = timedelta(minutes=JWT_EXPIRES_MINUTES)
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode: Dict[str, Any] = {"sub": subject, "exp": int(expire.timestamp())}
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token() -> Tuple[str, str, str, datetime]:
    """
    Tạo refresh token với định dạng: <token_id>.<secret>
    Trả về tuple (token_str, token_id, hashed_secret, expires_at)
    """
    token_id = uuid4().hex
    secret = secrets.token_urlsafe(32)
    token = f"{token_id}.{secret}"
    hashed_secret = hash_password(secret)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRES_DAYS)
    return token, token_id, hashed_secret, expires_at


def parse_refresh_token(raw_token: str) -> Tuple[str, str]:
    """
    Tách token thành (token_id, secret). Ném ValueError nếu format sai.
    """
    try:
        token_id, secret = raw_token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid refresh token format") from exc
    if not token_id or not secret:
        raise ValueError("Invalid refresh token format")
    return token_id, secret


def decode_access_token(token: str) -> Dict[str, Any]:

    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc


def get_user_id_from_token(token: str) -> str:
    """Lấy user_id từ token"""
    payload = decode_access_token(token)
    return payload.get("sub")


