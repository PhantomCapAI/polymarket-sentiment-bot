from sqlalchemy import Column, String, Float, DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
import enum

from ..core.database import Base

class OrderTypeEnum(enum.Enum):
    MARKET = "market"
    LIMIT = "limit"

class DirectionEnum(enum.Enum):
    YES = "yes"
    NO = "no"

class TradeStatusEnum(enum.Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"

class Trade(Base):
    __tablename__ = "trades"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Relationships
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    signal_id = Column(UUID(as_uuid=True), ForeignKey("signals.id"), nullable=True)
    
    # Market Info
    market_id = Column(String(100), nullable=False, index=True)
    
    # Trade Details
    order_type = Column(Enum(OrderTypeEnum), nullable=False)
    position_size = Column(Float, nullable=False)
    direction = Column(Enum(DirectionEnum), nullable=False)
    
    # Pricing
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, default=0.0)
    
    # Status
    status = Column(Enum(TradeStatusEnum), nullable=False, default=TradeStatusEnum.PENDING)
    
    # External References
    order_id = Column(String(100), nullable=True)
    
    # Metadata
    notes = Column(Text)
    executed_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)
    
    # Relationships
    user = relationship("User", back_populates="trades")
    signal = relationship("Signal", back_populates="trades")
