from fastapi import FastAPI, Depends, Response
from sqlalchemy import Column, Integer, create_engine, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from pydantic import BaseModel
from typing import List
from datetime import datetime
import os
import json
import redis.asyncio as redis
from contextlib import asynccontextmanager
import asyncio

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
    pool_size=20,             # Higher pool per instance since we have fewer instances
    max_overflow=30,          # More overflow connections per instance
    pool_pre_ping=True,       # Verify connections before use
    pool_recycle=3600,        # Recycle connections every hour
    echo=False                # Set to True for SQL debugging
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

# Async Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Database Model
class Object(Base):
    __tablename__ = "object"
    
    id = Column(Integer, primary_key=True, index=True)
    # Object type (id)
    o_type = Column(Integer)
    # Object position (x, y, z)
    o_pos = Column(String, default="0,0,0")
    # Object rotation (x, y, z)
    o_rot = Column(String, default="0,0,0")

# Pydantic Model
class ObjectCreate(BaseModel):
    o_type: int
    o_pos: str
    o_rot: str

class ObjectResponse(BaseModel):
    id: int
    o_type: int
    o_pos: str
    o_rot: str

    class Config:
        from_attributes = True

# Function to check if table schema matches our model
def check_table_schema():
    """Check if the existing table schema matches our SQLAlchemy model"""
    try:
        from sqlalchemy import inspect
        inspector = inspect(sync_engine)
        
        # Check if table exists
        if not inspector.has_table("object"):
            print("Table 'object' does not exist")
            return False
        
        # Get existing columns
        existing_columns = inspector.get_columns("object")
        existing_column_names = {col['name'] for col in existing_columns}
        
        # Expected columns from our model
        expected_columns = {'id', 'o_type', 'o_pos', 'o_rot'}
        
        # Check if all expected columns exist
        missing_columns = expected_columns - existing_column_names
        if missing_columns:
            print(f"Missing columns: {missing_columns}")
            return False
        
        # Check if there are extra columns (optional check)
        extra_columns = existing_column_names - expected_columns
        if extra_columns:
            print(f"Extra columns found: {extra_columns}")
            # You might want to return False here if you want strict schema matching
        
        print("Table schema matches the model")
        return True
        
    except Exception as e:
        print(f"Error checking schema: {e}")
        return False

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Check if we need to recreate tables
    try:
        if check_table_schema():
            print("Schema is up to date, no changes needed")
        else:
            print("Schema mismatch detected, recreating tables...")
            Base.metadata.drop_all(bind=sync_engine)
            print("Creating new tables...")
            Base.metadata.create_all(bind=sync_engine)
            print("Tables recreated successfully")
    except Exception as e:
        print(f"Error managing tables: {e}")
        # If there's any error, try to create tables anyway
        try:
            Base.metadata.create_all(bind=sync_engine)
            print("Tables created after error recovery")
        except Exception as e2:
            print(f"Failed to create tables: {e2}")
            raise e2
    yield

app = FastAPI(lifespan=lifespan)

# Async database dependency
async def get_db():
    async with AsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Store game data
@app.post("/add-object")
async def add_object(game_data: ObjectCreate, db: AsyncSession = Depends(get_db)):
    db_data = Object(**game_data.dict())
    db.add(db_data)
    await db.commit()
    
    # No cache invalidation - let cache expire naturally after 30 seconds
    # This allows better performance with constant POSTs, accepting some stale data
    
    return Response(status_code=201)

# Retrieve all game data
@app.get("/get-objects", response_model=List[ObjectResponse])
async def get_objects(db: AsyncSession = Depends(get_db)):
    # Try to get data from cache first
    cache_key = "objects:latest:100"
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data and isinstance(cached_data, str):
            # Parse cached JSON data and convert to ObjectResponse objects
            objects_data = json.loads(cached_data)
            print("Cache hit")
            return [ObjectResponse(**obj) for obj in objects_data]
    except Exception as e:
        # If Redis is not available, continue without cache
        print(f"Cache error: {e}")
    
    # If not in cache, get from database
    from sqlalchemy import select
    result = await db.execute(select(Object).order_by(Object.id.desc()).limit(100))
    objects = result.scalars().all()
    
    # Convert to dict format for caching
    objects_data = [{"id": obj.id, "o_type": obj.o_type, "o_pos": obj.o_pos, "o_rot": obj.o_rot} for obj in objects]
    
    # Cache the result for 30 seconds
    try:
        await redis_client.setex(cache_key, CACHE_DURATION, json.dumps(objects_data))
    except Exception as e:
        print(f"Cache set error: {e}")
    
    return [ObjectResponse(**obj) for obj in objects_data]