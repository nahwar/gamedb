from fastapi import FastAPI, Depends
from sqlalchemy import Column, Integer, create_engine, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import List
from datetime import datetime
import os
from contextlib import asynccontextmanager

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://username:password@localhost:5432/gamedb")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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
    create_date = Column(DateTime, default=datetime.now())

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
    create_date: datetime

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

# Store game data
@app.post("/add-object/", response_model=ObjectResponse)
def add_object(game_data: ObjectCreate, db: Session = Depends(get_db)):
    db_data = Object(**game_data.dict())
    db.add(db_data)
    db.commit()
    db.refresh(db_data)
    return db_data

# Retrieve all game data
@app.get("/get-objects/", response_model=List[ObjectResponse])
def get_objects(db: Session = Depends(get_db)):
    return db.query(Object).all()