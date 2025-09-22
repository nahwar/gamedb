from fastapi import FastAPI, Depends, Response
from sqlalchemy import Column, Integer, create_engine, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import List
from datetime import datetime
import os
import json
import redis
from contextlib import asynccontextmanager

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://username:password@localhost:5432/gamedb")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Redis setup
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

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(lifespan=lifespan)

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Health check endpoint
@app.get("/health")
def health_check():
    return {"status": "healthy"}

# Store game data
@app.post("/add-object")
def add_object(game_data: ObjectCreate, db: Session = Depends(get_db)):
    db_data = Object(**game_data.dict())
    db.add(db_data)
    db.commit()
    
    # Invalidate cache when new object is added
    try:
        redis_client.delete("objects:latest:100")
    except Exception as e:
        print(f"Cache invalidation error: {e}")
    
    return Response(status_code=201)

# Retrieve all game data
@app.get("/get-objects", response_model=List[ObjectResponse])
def get_objects(db: Session = Depends(get_db)):
    # Try to get data from cache first
    cache_key = "objects:latest:100"
    try:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            # Parse cached JSON data and convert to ObjectResponse objects
            objects_data = json.loads(cached_data)
            print("Cache hit")
            return [ObjectResponse(**obj) for obj in objects_data]
    except Exception as e:
        # If Redis is not available, continue without cache
        print(f"Cache error: {e}")
    
    # If not in cache, get from database
    objects = db.query(Object).order_by(Object.id.desc()).limit(100).all()
    
    # Convert to dict format for caching
    objects_data = [{"id": obj.id, "o_type": obj.o_type, "o_pos": obj.o_pos, "o_rot": obj.o_rot} for obj in objects]
    
    # Cache the result for 60 seconds
    try:
        redis_client.setex(cache_key, 60, json.dumps(objects_data))
    except Exception as e:
        print(f"Cache set error: {e}")
    
    return objects