from app.repositories.friend_repository import FriendRepository
from app.repositories.user_repository import UserRepository
from datetime import datetime
from typing import List
from bson import ObjectId

class FriendService:
    def __init__(self, friend_repo: FriendRepository, user_repo: UserRepository):
        self.friend_repo = friend_repo
        self.user_repo = user_repo

    async def send_friend_request(self, from_user: str, to_user: str):
        request = await self.friend_repo.get_friend_request(from_user, to_user)
        if request:
            return False  # đã gửi rồi
        return await self.friend_repo.create_friend_request(from_user, to_user)

    async def accept_friend_request(self, from_user: str, to_user: str):
        request = await self.friend_repo.get_friend_request(from_user, to_user)
        if not request or request["status"] != "pending":
            return False
        await self.friend_repo.update_request_status(request["_id"], "accepted")
        # cập nhật friends cho cả hai user
        from_doc = await self.user_repo.get_user_by_id(from_user)
        to_doc = await self.user_repo.get_user_by_id(to_user)
        if not from_doc or not to_doc:
            return False
        # dùng $addToSet để tránh trùng, và đảm bảo _id là ObjectId
        await self.user_repo._collection.update_one(
            {"_id": ObjectId(from_user)}, {"$addToSet": {"friends": to_user}}
        )
        await self.user_repo._collection.update_one(
            {"_id": ObjectId(to_user)}, {"$addToSet": {"friends": from_user}}
        )
        return True

    async def cancel_friend_request(self, from_user: str, to_user: str):
        request = await self.friend_repo.get_friend_request(from_user, to_user)
        if not request:
            return False
        return await self.friend_repo.delete_friend_request(request["_id"])

    async def get_friend_list(self, user_id: str) -> List[str]:
        return await self.friend_repo.list_friends(user_id)

    async def get_received_requests(self, user_id: str):
        return await self.friend_repo.list_received_requests(user_id)

    async def unfriend(self, user_id: str, friend_id: str) -> bool:
        # đảm bảo cả hai user tồn tại
        u1 = await self.user_repo.get_user_by_id(user_id)
        u2 = await self.user_repo.get_user_by_id(friend_id)
        if not u1 or not u2:
            return False
        return await self.friend_repo.unfriend(user_id, friend_id)
