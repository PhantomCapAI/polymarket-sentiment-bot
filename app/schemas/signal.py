from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional
from enum import Enum
import uuid

class DirectionEnum(str, Enum):
    YES = "YES"
    NO = "NO"

class SignalStatusEnum(str, Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    IGNORED = "ignored"

class SignalCreate(BaseModel):
    market_id: str = Field(..., min_length=1, max_length=100)
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    direction: DirectionEnum
    position_size: float = Field(..., gt=0, le=10000)
    threshold: float = Field(..., ge=0.0, le=1.0)
    news_sentiment: Optional[float] = Field(0.0, ge=-1.0, le=1.0)
    social_sentiment: Optional[float] = Field(0.0, ge=-1.0, le=1.0)
    market_sentiment: Optional[float] = Field(0.0, ge=-1.0, le=1.0)
    claude_analysis: Optional[str] = Field(None, max_length=1000)

    @validator('position_size')
    def validate_position_size(cls, v):
        if v <= 0:
            raise ValueError('Position size must be positive')
        return v

class SignalResponse(BaseModel):
    id: uuid.UUID
    generated_at: datetime
    market_id: str
    sentiment_score: float
    confidence_score: float
    direction: DirectionEnum
    position_size: float
    threshold: float
    status: SignalStatusEnum
    news_sentiment: float
    social_sentiment: float
    market_sentiment: float
    claude_analysis: Optional[str]
    
    class Config:
        from_attributes = True
