from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database.connection import close_mongo_connection, connect_to_mongo, get_database
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router


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


@app.get("/")
async def root():

    db = get_database()
    collections = await db.list_collection_names()
    return {"message": "Connected to MongoDB!", "collections": collections}


