from typing import AsyncGenerator, Optional

import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


load_dotenv()

_mongo_client: Optional[AsyncIOMotorClient] = None
_mongo_db: Optional[AsyncIOMotorDatabase] = None


def _get_mongo_uri() -> str:

    # Prefer unified MONGO_URL if provided (.env style)
    uri = os.getenv("MONGO_URL") or os.getenv("MONGODB_URI")
    if uri:
        return uri
    host = os.getenv("MONGODB_HOST", "localhost")
    port = os.getenv("MONGODB_PORT", "27017")
    username = os.getenv("MONGODB_USER")
    password = os.getenv("MONGODB_PASSWORD")
    if username and password:
        return f"mongodb://{username}:{password}@{host}:{port}"
    return f"mongodb://{host}:{port}"


def _get_db_name() -> str:

    # Prefer DB_NAME if provided (.env style)
    return os.getenv("DB_NAME") or os.getenv("MONGODB_DB", "fastapi_db")


async def connect_to_mongo() -> None:

    global _mongo_client, _mongo_db
    if _mongo_client is not None:
        return
    uri = _get_mongo_uri()
    
    # Fix SSL error với Python 3.14 - thêm các tham số compatibility
    try:
        _mongo_client = AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=30000,
            tlsAllowInvalidCertificates=True  # Bỏ qua lỗi SSL certificate trên Windows
        )
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        raise
    
    _mongo_db = _mongo_client[_get_db_name()]


async def close_mongo_connection() -> None:

    global _mongo_client, _mongo_db
    if _mongo_client is not None:
        _mongo_client.close()
    _mongo_client = None
    _mongo_db = None


def get_database() -> AsyncIOMotorDatabase:

    if _mongo_db is None:
        raise RuntimeError("MongoDB is not connected. Ensure lifespan events run or call connect_to_mongo().")
    return _mongo_db


async def mongo_db_dependency() -> AsyncGenerator[AsyncIOMotorDatabase, None]:

    yield get_database()


