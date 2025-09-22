from fastapi import FastAPI, Depends
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import List

# Database setup
DATABASE_URL = "postgresql://username:password@localhost:5432/gamedb"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database Model
class GameData(Base):
    __tablename__ = "game_data"
    
    id = Column(Integer, primary_key=True, index=True)
    data = Column(String)  # Store your game data as JSON string or however you need

# Pydantic Model
class GameDataCreate(BaseModel):
    data: str

class GameDataResponse(BaseModel):
    id: int
    data: str
    
    class Config:
        from_attributes = True

# Create tables
Base.metadata.create_all(bind=engine)

# FastAPI app
app = FastAPI()

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Store game data
@app.post("/game-data/", response_model=GameDataResponse)
def create_game_data(game_data: GameDataCreate, db: Session = Depends(get_db)):
    db_data = GameData(data=game_data.data)
    db.add(db_data)
    db.commit()
    db.refresh(db_data)
    return db_data

# Retrieve all game data
@app.get("/game-data/", response_model=List[GameDataResponse])
def get_game_data(db: Session = Depends(get_db)):
    return db.query(GameData).all()