from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase


class MediaRepository:
    """Repository for storing encrypted media metadata with filesystem blobs."""

    def __init__(self, db: AsyncIOMotorDatabase, storage_path: str | Path) -> None:
        self._db = db
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

    @property
    def collection(self):
        return self._db["media_files"]

    async def save_media(
        self,
        conversation_id: str,
        uploader_id: str,
        data: bytes,
        iv: str,
        mime_type: str,
        size: int,
    ) -> str:
        media_id = ObjectId()
        extension = self._guess_extension(mime_type)
        filename = f"{media_id}{extension}"
        file_path = self._storage_path / filename
        file_path.write_bytes(data)

        doc = {
            "_id": media_id,
            "conversation_id": conversation_id,
            "uploader_id": uploader_id,
            "path": filename,
            "iv": iv,
            "mime_type": mime_type,
            "size": size,
            "created_at": datetime.now(timezone.utc),
        }
        await self.collection.insert_one(doc)
        return str(media_id)

    async def get_media(self, media_id: str) -> Optional[dict]:
        try:
            oid = ObjectId(media_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"_id": oid})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        relative_path = doc.get("path")
        if relative_path:
            doc["file_path"] = str(self._storage_path / relative_path)
        return doc

    def _guess_extension(self, mime_type: str) -> str:
        mapping = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "audio/mp4": ".m4a",
            "audio/m4a": ".m4a",
            "audio/aac": ".m4a",
            "audio/ogg": ".ogg",
        }
        return mapping.get(mime_type.lower(), ".bin")

