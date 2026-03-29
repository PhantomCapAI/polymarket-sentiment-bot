from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

class OrderTypeEnum(str, Enum):
    MARKET = "market"
    LIMIT = "limit"

class DirectionEnum(str, Enum):
    YES = "yes"
    NO = "no"

class TradeStatusEnum(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"

class TradeResponse(BaseModel):
    id: str
    market_id: str
    signal_id: Optional[str]
    order_type: OrderTypeEnum
    position_size: float
    direction: DirectionEnum
    entry_price: Optional[float]
    exit_price: Optional[float]
    pnl: float
    status: TradeStatusEnum
    order_id: Optional[str]
    notes: Optional[str]
    executed_at: datetime
    closed_at: Optional[datetime]
    
    class Config:
        from_attributes = True
