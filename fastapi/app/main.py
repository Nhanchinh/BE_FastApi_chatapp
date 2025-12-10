from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.database.connection import close_mongo_connection, connect_to_mongo, get_database
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.friends import router as friends_router
from app.routers.chat import router as chat_router
from app.routers.conversations import router as conversations_router
from app.routers.presence import router as presence_router
from app.routers.devices import router as devices_router
from app.routers.users import router as users_router
from app.routers.conversation_keys import router as conversation_keys_router
from app.routers.media import router as media_router
from app.routers.fcm import router as fcm_router
from app.routers.fcm_test import router as fcm_test_router
from app.routers.zego import router as zego_router
from app.utils.rate_limiter import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):

    await connect_to_mongo()
    try:
        yield
    finally:
        await close_mongo_connection()


app = FastAPI(title="FastAPI Auth with MongoDB", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):

    return JSONResponse(
        status_code=429,
        content={"detail": "Too Many Requests. Please try again later."}
    )


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(friends_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(presence_router)
app.include_router(devices_router)
app.include_router(users_router)
app.include_router(conversation_keys_router)
app.include_router(media_router)
app.include_router(fcm_router)
app.include_router(fcm_test_router)  # Test endpoint - remove in production
app.include_router(zego_router)


@app.get("/")
async def root():

    db = get_database()
    collections = await db.list_collection_names()
    return {"message": "Connected to MongoDB!", "collections": collections}


