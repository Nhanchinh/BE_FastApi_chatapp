from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database.connection import close_mongo_connection, connect_to_mongo, get_database
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.friends import router as friends_router
from app.routers.chat import router as chat_router
from app.routers.conversations import router as conversations_router
from app.routers.presence import router as presence_router
from app.routers.devices import router as devices_router


@asynccontextmanager
async def lifespan(app: FastAPI):

    await connect_to_mongo()
    try:
        yield
    finally:
        await close_mongo_connection()


app = FastAPI(title="FastAPI Auth with MongoDB", lifespan=lifespan)


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(friends_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(presence_router)
app.include_router(devices_router)


@app.get("/")
async def root():

    db = get_database()
    collections = await db.list_collection_names()
    return {"message": "Connected to MongoDB!", "collections": collections}


