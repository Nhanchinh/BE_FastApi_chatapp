from datetime import datetime, timezone, timedelta
from typing import Optional


class LoginAttemptsRepository:
    """
    Repository để quản lý số lần login sai và lockout theo email (User ID).
    """
    
    COLLECTION_NAME = "login_attempts"
    MAX_ATTEMPTS = 5  # Số lần sai tối đa trước khi khóa
    LOCKOUT_MINUTES = 5  # Thời gian khóa (phút)
    
    def __init__(self, db):
        self.collection = db[self.COLLECTION_NAME]
    
    async def get_attempts(self, email: str) -> Optional[dict]:
        """Lấy thông tin login attempts của email"""
        email_key = email.strip().lower()
        return await self.collection.find_one({"email": email_key})
    
    async def is_locked(self, email: str) -> tuple[bool, Optional[int]]:
        """
        Kiểm tra email có bị khóa không.
        Returns: (is_locked, remaining_seconds)
        """
        record = await self.get_attempts(email)
        if not record:
            return False, None
        
        locked_until = record.get("locked_until")
        if not locked_until:
            return False, None
        
        # Ensure timezone aware
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        if now < locked_until:
            remaining = int((locked_until - now).total_seconds())
            return True, remaining
        
        return False, None
    
    async def increment_attempts(self, email: str) -> tuple[int, bool, Optional[int]]:
        """
        Tăng counter khi login sai.
        Returns: (current_attempts, is_now_locked, lockout_seconds)
        """
        email_key = email.strip().lower()
        now = datetime.now(timezone.utc)
        
        record = await self.get_attempts(email)
        
        if not record:
            # Tạo mới
            await self.collection.insert_one({
                "email": email_key,
                "attempts": 1,
                "locked_until": None,
                "last_attempt": now,
            })
            return 1, False, None
        
        new_attempts = record.get("attempts", 0) + 1
        
        # Kiểm tra có cần khóa không
        if new_attempts >= self.MAX_ATTEMPTS:
            locked_until = now + timedelta(minutes=self.LOCKOUT_MINUTES)
            await self.collection.update_one(
                {"email": email_key},
                {
                    "$set": {
                        "attempts": new_attempts,
                        "locked_until": locked_until,
                        "last_attempt": now,
                    }
                }
            )
            return new_attempts, True, self.LOCKOUT_MINUTES * 60
        
        # Chưa đến ngưỡng khóa
        await self.collection.update_one(
            {"email": email_key},
            {
                "$set": {
                    "attempts": new_attempts,
                    "last_attempt": now,
                }
            }
        )
        return new_attempts, False, None
    
    async def reset_attempts(self, email: str) -> None:
        """Reset counter về 0 khi login đúng"""
        email_key = email.strip().lower()
        await self.collection.update_one(
            {"email": email_key},
            {
                "$set": {
                    "attempts": 0,
                    "locked_until": None,
                }
            }
        )
    
    async def unlock_user(self, email: str) -> None:
        """Admin unlock user manually"""
        await self.reset_attempts(email)
