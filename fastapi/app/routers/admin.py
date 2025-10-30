from fastapi import APIRouter, Depends, HTTPException, status

from app.database.connection import mongo_db_dependency
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserPublic
from app.services.user_service import UserService
from app.utils.dependencies import get_current_admin_user


router = APIRouter(prefix="/admin", tags=["admin"])


async def get_user_service(db = Depends(mongo_db_dependency)) -> UserService:
    """Dependency inject UserService với UserRepository"""
    user_repo = UserRepository(db)
    return UserService(user_repo)


@router.get("/users", response_model=list[UserPublic])
async def get_all_users(
    user_service: UserService = Depends(get_user_service),
    current_admin: dict = Depends(get_current_admin_user)
):
    """
    API Admin: Lấy tất cả users
    - Yêu cầu: Đăng nhập với role admin
    """
    try:
        users = await user_service.get_all_users()
        return users
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching users: {str(e)}"
        )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    user_service: UserService = Depends(get_user_service),
    current_admin: dict = Depends(get_current_admin_user)
):
    """
    API Admin: Xóa user theo ID
    - Yêu cầu: Đăng nhập với role admin
    """
    try:
        await user_service.delete_user(user_id)
        return None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting user: {str(e)}"
        )

