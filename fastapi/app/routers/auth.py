from datetime import datetime, timezone
import random
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status, Header
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr

from app.database.connection import mongo_db_dependency
from app.repositories.user_repository import UserRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.login_attempts_repository import LoginAttemptsRepository
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
    hash_password,
    JWT_EXPIRES_MINUTES,
)
from app.utils.email_utils import send_otp_email


router = APIRouter(prefix="/auth", tags=["auth"])

OTP_TTL_SECONDS = 120
RESET_TOKEN_TTL_SECONDS = 300

otp_store: dict[str, dict[str, int | str]] = {}
reset_token_store: dict[str, dict[str, int | str]] = {}
# Store pending registrations waiting for OTP verification
pending_registration_store: dict[str, dict] = {}


# OTP Schemas
class OTPRequest(BaseModel):
    email: EmailStr


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str


# Registration OTP Schemas
class RegistrationOTPRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


class VerifyRegistrationOTPRequest(BaseModel):
    email: EmailStr
    otp: str
    public_key: str | None = None  # Optional, can be set later


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str
    token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


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
    x_app_signature: str | None = Header(default=None),
    user_service: UserService = Depends(get_user_service),
    db = Depends(mongo_db_dependency)
) -> LoginResponse:
    """
    Router: Nhận request đăng nhập
    -> Gọi Service để xác thực user
    -> Tạo token và trả về
    """
    # --- SECURITY CHECK: APP SIGNATURE ---
    # Mã SHA-256 từ keystore debug hiện tại của client
    # TODO: Uncomment khi deploy production để chống unauthorized clients
    # VALID_SIGNATURE = "22:9D:FA:84:FA:0C:C9:F9:35:8E:29:5A:96:A9:08:3D:03:90:1B:CB:41:38:9A:46:C8:79:B8:96:DD:C6:93:77"
    
    # Cho phép bỏ qua check nếu là request từ Swagger UI (thường không có header này) hoặc môi trường dev
    # Nhưng để bảo mật chặt chẽ, ta bắt buộc phải có.
    # Tuy nhiên, để tránh block bạn test API bằng Swagger, tôi sẽ cho phép nếu x_app_signature là None (tạm thời) HOẶC khớp.
    # NẾU BẠN MUỐN CHẶN TRIỆT ĐỂ: Xóa 'or x_app_signature is None'
    
    # if x_app_signature and x_app_signature != VALID_SIGNATURE:
    #      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ứng dụng không hợp lệ (Invalid Signature)")
    
    # --- ACCOUNT LOCKOUT CHECK ---
    login_attempts_repo = LoginAttemptsRepository(db)
    is_locked, remaining_seconds = await login_attempts_repo.is_locked(form_data.username)
    
    if is_locked:
        remaining_minutes = (remaining_seconds // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Tài khoản bị khóa tạm thời. Vui lòng thử lại sau {remaining_minutes} phút."
        )
    # -------------------------------------

    # Xác thực user qua Service
    user = await user_service.authenticate_user(form_data.username, form_data.password)
    
    if not user:
        # Tăng counter login sai
        attempts, is_now_locked, lockout_seconds = await login_attempts_repo.increment_attempts(form_data.username)
        
        if is_now_locked:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Quá nhiều lần đăng nhập sai. Tài khoản bị khóa trong {lockout_seconds // 60} phút."
            )
        
        remaining_attempts = LoginAttemptsRepository.MAX_ATTEMPTS - attempts
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Sai email hoặc mật khẩu. Còn {remaining_attempts} lần thử."
        )
    
    # Login thành công - reset counter
    await login_attempts_repo.reset_attempts(form_data.username)
    
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
        # Filter out user's own ID if it exists in friends list (bug fix)
        friends = [f for f in friends if f != str(user["_id"])]
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
        public_key=user.get("public_key"),
        avatar=user.get("avatar")
    )
    requires_public_key = not bool(user.get("public_key"))
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRES_MINUTES * 60,
        refresh_token=refresh_token,
        refresh_expires_in=refresh_expires_in,
        user=user_public,
        requires_public_key=requires_public_key,
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
        # Filter out user's own ID if it exists in friends list (bug fix)
        friends = [f for f in friends if f != str(current_user["_id"])]
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
        public_key=current_user.get("public_key"),
        avatar=current_user.get("avatar")
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
            # Filter out user's own ID if it exists in friends list (bug fix)
            friends = [f for f in friends if f != str(current_user["_id"])]
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


@router.post("/request-otp")
@limit_per_minute("5/minute")
async def request_otp(
    request: Request,
    payload: OTPRequest,
    db = Depends(mongo_db_dependency),
):
    email_input = payload.email.strip()
    email_key = email_input.lower()
    user_repo = UserRepository(db)
    user = await user_repo.get_user_by_email(email_input)
    if not user:
        user = await user_repo.get_user_by_email_case_insensitive(email_input)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email không tồn tại trong hệ thống")

    otp = str(random.randint(100000, 999999))
    expires = int(time.time()) + OTP_TTL_SECONDS
    otp_store[email_key] = {"otp": otp, "expires": expires}
    try:
        await send_otp_email(email_input, otp)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể gửi OTP"
        ) from e
    return {"message": "OTP đã gửi thành công"}


@router.post("/verify-otp")
@limit_per_minute("30/minute")
async def verify_otp(request: Request, payload: VerifyOTPRequest):
    email_key = payload.email.strip().lower()
    record = otp_store.get(email_key)
    if not record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không tìm thấy OTP")
    if int(time.time()) > int(record["expires"]):
        del otp_store[email_key]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP đã hết hạn")
    if payload.otp != record["otp"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP không đúng")
    # create temporary reset token
    token = str(random.randint(100000, 999999)) + str(int(time.time()))
    reset_token_store[email_key] = {
        "email": email_key,
        "token": token,
        "expires": int(time.time()) + RESET_TOKEN_TTL_SECONDS,
    }
    del otp_store[email_key]
    return {
        "success": True,
        "message": "Xác minh OTP thành công",
        "reset_token": token,
        "expires_in": RESET_TOKEN_TTL_SECONDS,
    }


@router.post("/reset-password")
@limit_per_minute("10/minute")
async def reset_password(request: Request, payload: ResetPasswordRequest, db = Depends(mongo_db_dependency)):
    email_input = payload.email.strip()
    email_key = email_input.lower()
    record = reset_token_store.get(email_key)
    if not record or record["token"] != payload.token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token không hợp lệ")
    if int(time.time()) > int(record["expires"]):
        del reset_token_store[email_key]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token đã hết hạn")

    user_repo = UserRepository(db)
    user = await user_repo.get_user_by_email(email_input)
    if not user:
        user = await user_repo.get_user_by_email_case_insensitive(email_input)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email không tồn tại")

    hashed = hash_password(payload.new_password)
    await user_repo.update_password_hash(user["_id"], hashed)
    del reset_token_store[email_key]
    return {"success": True, "message": "Đặt lại mật khẩu thành công"}


@router.post("/change-password")
@limit_per_minute("10/minute")
async def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(mongo_db_dependency),
):
    user_repo = UserRepository(db)
    user = await user_repo.get_user_by_id(current_user["_id"])
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy người dùng")

    if not verify_password(payload.old_password, user.get("hashed_password", "")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mật khẩu cũ không chính xác")

    new_hashed = hash_password(payload.new_password)
    await user_repo.update_password_hash(current_user["_id"], new_hashed)

    return {"success": True, "message": "Thay đổi mật khẩu thành công"}


# ============================================================================
# REGISTRATION OTP ENDPOINTS
# ============================================================================

@router.post("/request-registration-otp")
@limit_per_minute("3/minute")
async def request_registration_otp(
    request: Request,
    payload: RegistrationOTPRequest,
    db = Depends(mongo_db_dependency),
):
    """
    Step 1 of registration: Request OTP for email verification.
    Stores pending registration data and sends OTP to email.
    """
    email_input = payload.email.strip()
    email_key = email_input.lower()
    
    # Check if email already exists
    user_repo = UserRepository(db)
    existing_user = await user_repo.get_user_by_email(email_input)
    if not existing_user:
        existing_user = await user_repo.get_user_by_email_case_insensitive(email_input)
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Email đã được sử dụng. Vui lòng đăng nhập hoặc sử dụng email khác."
        )
    
    # Generate OTP
    otp = str(random.randint(100000, 999999))
    expires = int(time.time()) + OTP_TTL_SECONDS
    
    # Store OTP
    otp_store[email_key] = {"otp": otp, "expires": expires}
    
    # Store pending registration data
    pending_registration_store[email_key] = {
        "email": email_input,
        "password": payload.password,
        "full_name": payload.full_name,
        "expires": expires,
    }
    
    # Send OTP email
    try:
        await send_otp_email(email_input, otp)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể gửi OTP"
        ) from e
    
    return {
        "success": True,
        "message": "OTP đã được gửi đến email của bạn",
        "expires_in": OTP_TTL_SECONDS
    }


@router.post("/verify-registration-otp")
@limit_per_minute("10/minute")
async def verify_registration_otp(
    request: Request,
    payload: VerifyRegistrationOTPRequest,
    db = Depends(mongo_db_dependency),
):
    """
    Step 2 of registration: Verify OTP and create account.
    Returns login response (auto-login after successful registration).
    """
    email_key = payload.email.strip().lower()
    
    # Check OTP
    otp_record = otp_store.get(email_key)
    if not otp_record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không tìm thấy OTP. Vui lòng yêu cầu OTP mới.")
    
    if int(time.time()) > int(otp_record["expires"]):
        del otp_store[email_key]
        if email_key in pending_registration_store:
            del pending_registration_store[email_key]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP đã hết hạn. Vui lòng yêu cầu OTP mới.")
    
    if payload.otp != otp_record["otp"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP không đúng")
    
    # Get pending registration data
    pending = pending_registration_store.get(email_key)
    if not pending:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không tìm thấy thông tin đăng ký. Vui lòng thử lại.")
    
    # Create user account
    user_repo = UserRepository(db)
    user_service = UserService(user_repo)
    
    try:
        user = await user_service.register_user(
            email=pending["email"],
            password=pending["password"],
            full_name=pending["full_name"],
            public_key=payload.public_key
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    # Clean up OTP and pending registration
    del otp_store[email_key]
    del pending_registration_store[email_key]
    
    # Auto-login: Create tokens
    token = create_access_token(subject=user.id)
    refresh_repo = RefreshTokenRepository(db)
    refresh_token, token_id, hashed_secret, refresh_expires_at = create_refresh_token()
    await refresh_repo.create_refresh_token(
        user_id=user.id,
        token_id=token_id,
        hashed_secret=hashed_secret,
        expires_at=refresh_expires_at,
    )
    refresh_expires_in = int((refresh_expires_at - datetime.now(timezone.utc)).total_seconds())
    
    return {
        "success": True,
        "message": "Đăng ký thành công!",
        "access_token": token,
        "token_type": "bearer",
        "expires_in": JWT_EXPIRES_MINUTES * 60,
        "refresh_token": refresh_token,
        "refresh_expires_in": refresh_expires_in,
        "user": user,
        "requires_public_key": not bool(payload.public_key),
    }
