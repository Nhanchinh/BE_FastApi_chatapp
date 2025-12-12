from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database.connection import mongo_db_dependency
from app.repositories.notification_repository import NotificationRepository
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


def get_repo(db=Depends(mongo_db_dependency)) -> NotificationRepository:
    return NotificationRepository(db)


@router.get("")
async def list_notifications(
    limit: int = Query(6, ge=1, le=50),
    cursor: str | None = None,
    current_user: dict = Depends(get_current_user),
    repo: NotificationRepository = Depends(get_repo),
):
    items, next_cursor = await repo.list_notifications(
        user_id=current_user["_id"], limit=limit, cursor=cursor
    )
    return {"items": items, "next_cursor": next_cursor}


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    repo: NotificationRepository = Depends(get_repo),
):
    ok = await repo.mark_read(notification_id, current_user["_id"])
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return {"message": "Marked as read"}


@router.post("/read_all")
async def mark_all_notifications_read(
    current_user: dict = Depends(get_current_user),
    repo: NotificationRepository = Depends(get_repo),
):
    updated = await repo.mark_all_read(current_user["_id"])
    return {"updated": updated}

