from typing import Optional

from app.repositories.user_repository import UserRepository
from app.schemas.user import UserPublic
from app.utils.security import hash_password, verify_password


class UserService:
    """Service layer xử lý logic nghiệp vụ cho User"""

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def register_user(self, email: str, password: str, full_name: Optional[str]) -> UserPublic:
        """
        Đăng ký user mới
        - Validate email đã tồn tại chưa
        - Hash password
        - Tạo user trong DB
        """
        # Kiểm tra email đã tồn tại
        existing = await self.user_repository.get_user_by_email(email)
        if existing:
            raise ValueError("Email already registered")

        # Hash password trước khi lưu
        hashed_password = hash_password(password)

        # Tạo user mới
        new_id = await self.user_repository.create_user(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
        )

        return UserPublic(id=new_id, email=email, full_name=full_name)

    async def authenticate_user(self, email: str, password: str) -> dict:
        """
        Xác thực user đăng nhập
        - Tìm user theo email
        - Verify password
        - Trả về user data nếu hợp lệ
        """
        # Lấy user từ DB
        user = await self.user_repository.get_user_by_email(email)
        if not user:
            return None

        # Verify password
        if not verify_password(password, user.get("hashed_password", "")):
            return None

        return user

    async def get_or_create_test_user(self, email: str, password: str, full_name: str) -> UserPublic:
        """
        Tạo hoặc lấy test user (để seed data)
        - Kiểm tra user đã tồn tại chưa
        - Nếu chưa có thì tạo mới
        - Nếu có rồi thì trả về user hiện tại
        """
        # Kiểm tra user đã tồn tại
        existing = await self.user_repository.get_user_by_email(email)
        if existing:
            return UserPublic(
                id=existing["_id"],
                email=existing["email"],
                full_name=existing.get("full_name")
            )

        # Tạo user mới
        hashed_password = hash_password(password)
        new_id = await self.user_repository.create_user(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
        )

        return UserPublic(id=new_id, email=email, full_name=full_name)

