from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.database.connection import mongo_db_dependency
from app.repositories.user_repository import UserRepository
from app.schemas.user import Token, UserCreate, UserPublic, LoginResponse
from app.services.user_service import UserService
from app.utils.security import create_access_token, JWT_EXPIRES_MINUTES


router = APIRouter(prefix="/auth", tags=["auth"])


# Khởi tạo UserService ở đây để tái sử dụng
async def get_user_service(db = Depends(mongo_db_dependency)) -> UserService:
    """Dependency inject UserService với UserRepository"""
    user_repo = UserRepository(db)
    return UserService(user_repo)


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register_user(payload: UserCreate, user_service: UserService = Depends(get_user_service)) -> UserPublic:
    """
    Router: Nhận request đăng ký
    -> Gọi Service để xử lý logic
    """
    try:
        user = await user_service.register_user(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name
        )
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=LoginResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), user_service: UserService = Depends(get_user_service)) -> LoginResponse:
    """
    Router: Nhận request đăng nhập
    -> Gọi Service để xác thực user
    -> Tạo token và trả về
    """
    # Xác thực user qua Service
    user = await user_service.authenticate_user(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")
    
    # Tạo access token + đóng gói thông tin user
    token = create_access_token(subject=user["_id"])
    user_public = UserPublic(
        id=user["_id"],
        email=user["email"],
        full_name=user.get("full_name"),
        role=user.get("role", "user"),
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRES_MINUTES * 60,
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
