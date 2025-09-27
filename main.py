from fastapi import FastAPI, Depends, Response
from sqlalchemy import Column, Integer, create_engine, String, select, JSON, MetaData, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
import os
import orjson
import redis.asyncio as redis
from contextlib import asynccontextmanager
import asyncio
import gzip
from fastapi.responses import Response as FastAPIResponse

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

# Async Redis setup (binary-safe, store bytes directly)
# Use decode_responses=False so Redis returns bytes for binary blobs
# and set a reasonable max_connections to avoid exhausting connections.
redis_client = redis.from_url(REDIS_URL, decode_responses=False, max_connections=50)

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

class Message(Base):
    __tablename__ = "message"
    
    id = Column(Integer, primary_key=True, index=True)
    part1 = Column(String, default="")
    part2 = Column(String, default="")
    part3 = Column(String, default="")

class Phantom(Base):
    __tablename__ = "phantom"
    
    id = Column(Integer, primary_key=True, index=True)
    data = Column(JSON, default=[])

class MessageCreate(BaseModel):
    part1: str
    part2: str
    part3: str

class PhantomCreate(BaseModel):
    data: list[list[str]]

# Pydantic Model
class ObjectCreate(BaseModel):
    o_type: int
    o_pos: str
    o_rot: str

    @field_validator('o_pos', 'o_rot')
    @classmethod
    def validate_coordinates(cls, v):
        coords = v.split(",")
        if len(coords) != 3:
            raise ValueError("Coordinates must be in 'x,y,z' format")
        for coord in coords:
            try:
                float(coord.strip())
            except ValueError:
                raise ValueError("Coordinates must be floats")
        return v
        
class IncomingData(BaseModel):
    # obj and message are optional, but we require at least one to be provided
    obj: Optional[ObjectCreate] = None
    message: Optional[MessageCreate] = None
    phantom: PhantomCreate

    @model_validator(mode="before")
    @classmethod
    def ensure_obj_or_message(cls, values):
        # values is the raw input mapping before coercion
        if not values:
            raise ValueError("Incoming data must include at least one of 'obj' or 'message'.")
        obj = values.get('obj')
        message = values.get('message')
        if obj is None and message is None:
            raise ValueError("At least one of 'obj' or 'message' must be provided")
        return values

class ObjectResponse(BaseModel):
    id: int
    o_type: int
    o_pos: str
    o_rot: str

    class Config:
        from_attributes = True

class MessageResponse(BaseModel):
    id: int
    part1: str
    part2: str
    part3: str

    class Config:
        from_attributes = True

class PhantomResponse(BaseModel):
    id: int
    data: list[list[str]]

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
        if not inspector.has_table("message"):
            print("Table 'message' does not exist")
            return False
        if not inspector.has_table("phantom"):
            print("Table 'phantom' does not exist")
            return False
        
        # Get existing columns
        existing_columns = inspector.get_columns("object")
        existing_column_names = {col['name'] for col in existing_columns}
        expected_columns = {'id', 'o_type', 'o_pos', 'o_rot'}
        missing_columns = expected_columns - existing_column_names
        if missing_columns:
            print(f"Missing columns: {missing_columns}")
            return False
        extra_columns = existing_column_names - expected_columns
        if extra_columns:
            print(f"Extra columns found: {extra_columns}")

        existing_columns = inspector.get_columns("message")
        existing_column_names = {col['name'] for col in existing_columns}
        expected_columns = {'id', 'part1', 'part2', 'part3'}
        missing_columns = expected_columns - existing_column_names
        if missing_columns:
            print(f"Missing columns in 'message': {missing_columns}")
            return False
        extra_columns = existing_column_names - expected_columns
        if extra_columns:
            print(f"Extra columns found in 'message': {extra_columns}")

        existing_columns = inspector.get_columns("phantom")
        existing_column_names = {col['name'] for col in existing_columns}
        expected_columns = {'id', 'data'}
        missing_columns = expected_columns - existing_column_names
        if missing_columns:
            print(f"Missing columns in 'phantom': {missing_columns}")
            return False
        extra_columns = existing_column_names - expected_columns
        if extra_columns:
            print(f"Extra columns found in 'phantom': {extra_columns}")
        
        
        print("Table schema matches the model")
        return True
        
    except Exception as e:
        print(f"Error checking schema: {e}")
        return False

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create any missing tables in a robust way.
    # Instead of dropping everything (which can fail when objects/sequences
    # exist only partially), reflect existing DB state and create missing
    # tables one-by-one. If a sequence conflict occurs, drop the conflicting
    # sequence and retry creation.
    try:
        if check_table_schema():
            print("Schema is up to date, no changes needed")
        else:
            print("Schema mismatch detected, creating missing tables...")
            # Inspect existing tables
            inspector = sa_inspect(sync_engine)
            existing = set(inspector.get_table_names())

            # Create each table defined in our metadata if it's missing
            for tbl_name, table_obj in Base.metadata.tables.items():
                if tbl_name in existing:
                    continue
                try:
                    print(f"Creating table '{tbl_name}'...")
                    table_obj.create(bind=sync_engine, checkfirst=True)
                    print(f"Table '{tbl_name}' created")
                except IntegrityError as ie:
                    # Handle duplicate sequence/name errors by attempting to drop
                    # the conflicting sequence and retrying once.
                    msg = str(ie.orig) if hasattr(ie, 'orig') else str(ie)
                    print(f"IntegrityError creating '{tbl_name}': {msg}")
                    # Try to extract a sequence name like '<table>_id_seq'
                    # and drop it if present then retry creation.
                    try:
                        # naive pattern: look for '_id_seq' occurrences
                        if '_id_seq' in msg:
                            # find token containing _id_seq
                            parts = [p for p in msg.replace('(', ' ').replace(')', ' ').split() if '_id_seq' in p]
                            if parts:
                                seq_name = parts[0].strip(',;"')
                                print(f"Dropping conflicting sequence '{seq_name}' and retrying")
                                with sync_engine.connect() as conn:
                                    conn.execute(text(f"DROP SEQUENCE IF EXISTS {seq_name} CASCADE"))
                                    conn.commit()
                                # retry
                                table_obj.create(bind=sync_engine, checkfirst=True)
                                print(f"Table '{tbl_name}' created after dropping sequence")
                                continue
                    except Exception as e2:
                        print(f"Failed to drop sequence or retry create for '{tbl_name}': {e2}")
                    raise ie
                except ProgrammingError as pe:
                    # Some drivers may raise ProgrammingError for missing objects
                    print(f"ProgrammingError while creating '{tbl_name}': {pe}")
                    raise pe
            print("Table creation step complete")
    except Exception as e:
        # Log and continue startup — avoid crashing the whole app on transient
        # schema repair issues. Subsequent DB calls may still fail if schema is
        # inconsistent, but the server will start so operator can inspect logs.
        print(f"Error managing tables: {e}")
    yield

app = FastAPI(lifespan=lifespan)

# Note: We intentionally do manual gzip compression for the
# `/get-objects` response and store compressed bytes in Redis.
# Removing FastAPI's GZipMiddleware prevents double compression
# and gives us explicit control over caching compressed blobs.

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

# Retrieve all game data with compression
@app.get("/get-objects")
async def get_objects(db: AsyncSession = Depends(get_db)):
    # Try to get data from cache first
    cache_key = "last_data:compressed"
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            # With decode_responses=False, cached_data is bytes (binary-safe)
            print("Compressed cache hit")
            return FastAPIResponse(
                content=cached_data,
                media_type="application/json",
                headers={"Content-Encoding": "gzip"}
            )
    except Exception as e:
        print(f"Cache error: {e}")
    
    # If not in cache, get from database
    result = await db.execute(select(Object).order_by(Object.id.desc()).limit(200))
    objects = result.scalars().all()
    
    # Convert to dict format
    objects_data = [{"id": obj.id, "o_type": obj.o_type, "o_pos": obj.o_pos, "o_rot": obj.o_rot} for obj in objects]

    # Get messages
    result = await db.execute(select(Message).order_by(Message.id.desc()).limit(200))
    messages = result.scalars().all()
    messages_data = [{"id": msg.id, "part1": msg.part1, "part2": msg.part2, "part3": msg.part3} for msg in messages]

    # Get phantoms
    result = await db.execute(select(Phantom).order_by(Phantom.id.desc()).limit(20))
    phantoms = result.scalars().all()
    phantoms_data = [{"id": ph.id, "data": ph.data} for ph in phantoms]

    all_data = {
        "objects": objects_data,
        "messages": messages_data,
        "phantoms": phantoms_data
    }

    compressed_data = gzip.compress(orjson.dumps(all_data))

    # Cache the compressed result (store bytes directly)
    try:
        await redis_client.setex(cache_key, CACHE_DURATION, compressed_data)
    except Exception as e:
        print(f"Cache set error: {e}")
    
    return FastAPIResponse(
        content=compressed_data,
        media_type="application/json",
        headers={"Content-Encoding": "gzip"}
    )