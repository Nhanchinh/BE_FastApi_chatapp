from fastapi import APIRouter, Depends, HTTPException, Query
from app.database.connection import mongo_db_dependency
from app.repositories.user_repository import UserRepository
from app.services.user_service import UserService
from app.utils.dependencies import get_current_user


router = APIRouter(prefix="/users", tags=["users"])


def get_user_service(db = Depends(mongo_db_dependency)):
    user_repo = UserRepository(db)
    return UserService(user_repo)


@router.get("/search")
async def search_users(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50), prefix: bool = Query(False), current_user: dict = Depends(get_current_user), service: UserService = Depends(get_user_service)):
    results = await service.search_users(query=q, limit=limit, exclude_user_id=current_user["_id"], prefix=prefix)
    return {"items": results}


