from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.database.connection import mongo_db_dependency
from app.repositories.user_repository import UserRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.schemas.user import (
    UserCreate,
    UserPublic,
    LoginResponse,
    UserProfileUpdate,
    RefreshTokenRequest,
    RefreshTokenResponse,
)
from app.repositories.friend_repository import FriendRepository
from app.utils.dependencies import get_current_user
from app.services.user_service import UserService
from app.utils.rate_limiter import limit_per_minute
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    parse_refresh_token,
    verify_password,
    JWT_EXPIRES_MINUTES,
)


router = APIRouter(prefix="/auth", tags=["auth"])


# Khởi tạo UserService ở đây để tái sử dụng
async def get_user_service(db = Depends(mongo_db_dependency)) -> UserService:
    """Dependency inject UserService với UserRepository"""
    user_repo = UserRepository(db)
    return UserService(user_repo)


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
@limit_per_minute("3/minute")
async def register_user(
    request: Request,
    payload: UserCreate,
    user_service: UserService = Depends(get_user_service),
) -> UserPublic:
    """
    Router: Nhận request đăng ký
    -> Gọi Service để xử lý logic
    """
    try:
        user = await user_service.register_user(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            public_key=payload.public_key
        )
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=LoginResponse)
@limit_per_minute("5/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_service: UserService = Depends(get_user_service),
    db = Depends(mongo_db_dependency)
) -> LoginResponse:
    """
    Router: Nhận request đăng nhập
    -> Gọi Service để xác thực user
    -> Tạo token và trả về
    """
    # Xác thực user qua Service
    user = await user_service.authenticate_user(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")
    
    # Tạo access token + refresh token
    token = create_access_token(subject=user["_id"])
    refresh_repo = RefreshTokenRepository(db)
    refresh_token, token_id, hashed_secret, refresh_expires_at = create_refresh_token()
    await refresh_repo.create_refresh_token(
        user_id=user["_id"],
        token_id=token_id,
        hashed_secret=hashed_secret,
        expires_at=refresh_expires_at,
    )
    refresh_expires_in = int((refresh_expires_at - datetime.now(timezone.utc)).total_seconds())

    # Count friends (stored as array in users collection)
    friend_repo = FriendRepository(db)
    try:
        friends = await friend_repo.list_friends(str(user["_id"]))
        friend_count = len(friends)
    except Exception:
        friend_count = 0

    user_public = UserPublic(
        id=user["_id"],
        email=user["email"],
        full_name=user.get("full_name"),
        role=user.get("role", "user"),
        friend_count=friend_count,
        location=user.get("location"),
        hometown=user.get("hometown"),
        birth_year=user.get("birth_year"),
        public_key=user.get("public_key")
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRES_MINUTES * 60,
        refresh_token=refresh_token,
        refresh_expires_in=refresh_expires_in,
        user=user_public,
    )



@router.post("/seed-test-user", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def seed_test_user(user_service: UserService = Depends(get_user_service)) -> UserPublic:
    """
    Router: Seed test user
    -> Gọi Service để tạo hoặc lấy test user
    """
    user = await user_service.get_or_create_test_user(
        email="test@example.com",
        password="secret123",
        full_name="Test User",
        role="user"
    )
    return user


@router.post("/seed-admin", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def seed_admin_user(user_service: UserService = Depends(get_user_service)) -> UserPublic:
    """
    Router: Seed admin user
    -> Tạo hoặc lấy admin user để test
    """
    user = await user_service.get_or_create_test_user(
        email="admin@example.com",
        password="admin123",
        full_name="Admin User",
        role="admin"
    )
    return user


@router.get("/profile", response_model=UserPublic)
async def get_my_profile(
    current_user: dict = Depends(get_current_user),
    db = Depends(mongo_db_dependency)
) -> UserPublic:
    """Lấy thông tin profile của user đang đăng nhập"""
    friend_repo = FriendRepository(db)
    try:
        friends = await friend_repo.list_friends(str(current_user["_id"]))
        friend_count = len(friends)
    except Exception:
        friend_count = 0
    
    return UserPublic(
        id=current_user["_id"],
        email=current_user["email"],
        full_name=current_user.get("full_name"),
        role=current_user.get("role", "user"),
        location=current_user.get("location"),
        hometown=current_user.get("hometown"),
        birth_year=current_user.get("birth_year"),
        friend_count=friend_count,
        public_key=current_user.get("public_key")
    )


@router.patch("/profile", response_model=UserPublic)
async def update_profile(
    payload: UserProfileUpdate,
    current_user: dict = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
    db = Depends(mongo_db_dependency)
) -> UserPublic:
    """
    Cập nhật thông tin cá nhân của user đang đăng nhập
    - full_name: Họ và tên
    - location: Sống tại
    - hometown: Đến từ  
    - birth_year: Năm sinh
    """
    try:
        updates = payload.model_dump(exclude_unset=True)
        user = await user_service.update_user_profile(
            user_id=current_user["_id"],
            updates=updates
        )
        
        # Add friend count
        friend_repo = FriendRepository(db)
        try:
            friends = await friend_repo.list_friends(str(current_user["_id"]))
            user.friend_count = len(friends)
        except Exception:
            user.friend_count = 0
        
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/refresh", response_model=RefreshTokenResponse)
@limit_per_minute("60/minute")
async def refresh_tokens(
    request: Request,
    payload: RefreshTokenRequest,
    db = Depends(mongo_db_dependency)
) -> RefreshTokenResponse:
    """
    Đổi refresh token hợp lệ lấy access token mới (token rotation).
    """
    refresh_repo = RefreshTokenRepository(db)
    try:
        token_id, secret = parse_refresh_token(payload.refresh_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    stored = await refresh_repo.get_active_token(token_id)
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # MongoDB stores datetime as naive, convert to aware for comparison
    expires_at = stored.get("expires_at")
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    if expires_at <= datetime.now(timezone.utc):
        await refresh_repo.revoke_token(token_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    if not verify_password(secret, stored.get("hashed_secret", "")):
        await refresh_repo.revoke_token(token_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_repo = UserRepository(db)
    user = await user_repo.get_user_by_id(stored["user_id"])
    if not user:
        await refresh_repo.revoke_token(token_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Rotate token: revoke old, issue new one
    await refresh_repo.revoke_token(token_id)
    new_refresh_token, new_token_id, new_hashed_secret, refresh_expires_at = create_refresh_token()
    await refresh_repo.create_refresh_token(
        user_id=stored["user_id"],
        token_id=new_token_id,
        hashed_secret=new_hashed_secret,
        expires_at=refresh_expires_at,
    )

    access_token = create_access_token(subject=stored["user_id"])
    expires_in = JWT_EXPIRES_MINUTES * 60
    refresh_expires_in = int((refresh_expires_at - datetime.now(timezone.utc)).total_seconds())

    return RefreshTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        refresh_token=new_refresh_token,
        refresh_expires_in=refresh_expires_in,
    )
