import gzip
import os
from contextlib import asynccontextmanager
from typing import Optional
from uuid import UUID

import orjson
import redis.asyncio as redis
from fastapi import Depends, FastAPI, Response
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, model_validator
from sqlalchemy import JSON, Column, Integer, String, Uuid, create_engine, select, func
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base

# CONST
CACHE_DURATION = 30  # Cache duration in seconds

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://username:password@localhost:5432/gamedb")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Convert PostgreSQL URL to async version
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Async database engine for high concurrency
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)
AsyncSessionLocal = async_sessionmaker(
    async_engine, 
    class_=AsyncSession,
    expire_on_commit=False
)

# Keep sync engine for table creation
sync_engine = create_engine(
    DATABASE_URL,
    pool_size=4,
    max_overflow=6,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)
Base = declarative_base()

redis_client = redis.from_url(REDIS_URL, decode_responses=False, max_connections=50)

# Database Models
class Object(Base):
    __tablename__ = "object"
    
    id = Column(Integer, primary_key=True, index=True)
    u_uuid = Column(Uuid, index=True, nullable=False)
    # Object type (id)
    o_type = Column(Integer)
    # Object position (x, y, z)
    o_pos = Column(String, default="0,0,0")
    # Object rotation (x, y, z)
    o_rot = Column(String, default="0,0,0")

class Message(Base):
    __tablename__ = "message"
    
    id = Column(Integer, primary_key=True, index=True)
    u_uuid = Column(Uuid, index=True, nullable=False)
    m_pos = Column(String, default="0,0,0")
    part1 = Column(Integer, default=0)
    part2 = Column(Integer, default=0)
    part3 = Column(Integer, default=0)

class Phantom(Base):
    __tablename__ = "phantom"
    
    id = Column(Integer, primary_key=True, index=True)
    u_uuid = Column(Uuid, index=True, nullable=False)
    # Phantom data as JSON array of arrays
    # Example: [["pos1", "rot1"], ["pos2", "rot2"]]
    data = Column(JSON, default=[])

# Pydantic Models
class MessageCreate(BaseModel):
    u_uuid: UUID
    m_pos: str
    part1: int
    part2: int
    part3: int

class PhantomCreate(BaseModel):
    u_uuid: UUID
    data: list[list[str]]

# Pydantic Model
class ObjectCreate(BaseModel):
    u_uuid: UUID
    o_type: int
    o_pos: str
    o_rot: str
        
class IncomingData(BaseModel):
    obj: Optional[ObjectCreate] = None
    message: Optional[MessageCreate] = None
    phantom: PhantomCreate

    @model_validator(mode="before")
    @classmethod
    def ensure_obj_or_message(cls, values):
        # we want at least one of obj or message
        if not values:
            raise ValueError("Incoming data must include at least one of 'obj' or 'message'.")
        obj = values.get('obj')
        message = values.get('message')
        if obj is None and message is None:
            raise ValueError("At least one of 'obj' or 'message' must be provided")
        return values

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        inspector = sa_inspect(sync_engine)
        existing = set(inspector.get_table_names())

        for tbl_name, table_obj in Base.metadata.tables.items():
            if tbl_name in existing:
                continue
            try:
                print(f"Creating missing table '{tbl_name}'...")
                table_obj.create(bind=sync_engine, checkfirst=True)
                print(f"Table '{tbl_name}' created")
            except Exception as e:
                # Log and continue; don't crash the app on startup table creation
                print(f"Failed to create table '{tbl_name}': {e}")
        print("Table existence check complete")
    except Exception as e:
        print(f"Error during table existence check: {e}")
    yield

app = FastAPI(lifespan=lifespan)

# Async database dependency
async def get_db():
    async with AsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Store game data
@app.post("/add-object")
async def add_object(game_data: IncomingData, db: AsyncSession = Depends(get_db)):
    # Check if obj_data is valid
    if game_data.obj is not None:
        obj_data = Object(**game_data.obj.dict())
        db.add(obj_data)
    # Check if msg data is valid
    if game_data.message is not None:
        msg_data = Message(**game_data.message.dict())
        db.add(msg_data)
    # We always send phantom data
    db_data = Phantom(**game_data.phantom.dict())
    db.add(db_data)

    await db.commit()
    
    return Response("Created!!!", status_code=201)

# Retrieve last cached game data or retrieve
@app.get("/get-objects")
async def get_objects(db: AsyncSession = Depends(get_db)):
    # Try to get data from cache first
    cache_key = "last_data:compressed"
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            print("Compressed cache hit")
            return FastAPIResponse(
                content=cached_data,
                media_type="application/json",
                headers={"Content-Encoding": "gzip"}
            )
    except Exception as e:
        print(f"Cache error: {e}")
    
    # Cache miss
    # Get objects
    result = await db.execute(select(Object).order_by(Object.id.desc()).limit(200))
    objects = result.scalars().all()
    objects_data = [{"id": obj.id, "u_uuid": str(obj.u_uuid), "o_type": obj.o_type, "o_pos": obj.o_pos, "o_rot": obj.o_rot} for obj in objects]

    # Get messages
    result = await db.execute(select(Message).order_by(Message.id.desc()).limit(200))
    messages = result.scalars().all()
    messages_data = [{"id": msg.id, "u_uuid": str(msg.u_uuid), "m_pos": msg.m_pos, "part1": msg.part1, "part2": msg.part2, "part3": msg.part3} for msg in messages]

    # Get phantoms
    result = await db.execute(select(Phantom).order_by(func.random()).limit(20))
    phantoms = result.scalars().all()
    phantoms_data = [{"id": ph.id, "u_uuid": str(ph.u_uuid), "data": ph.data} for ph in phantoms]

    all_data = {
        "objects": objects_data,
        "messages": messages_data,
        "phantoms": phantoms_data
    }

    compressed_data = gzip.compress(orjson.dumps(all_data))

    # Cache the compressed result
    try:
        await redis_client.setex(cache_key, CACHE_DURATION, compressed_data)
    except Exception as e:
        print(f"Cache set error: {e}")
    
    return FastAPIResponse(
        content=compressed_data,
        media_type="application/json",
        headers={"Content-Encoding": "gzip"}
    )