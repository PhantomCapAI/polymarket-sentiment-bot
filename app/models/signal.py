from sqlalchemy import Column, String, Float, DateTime, Enum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ..core.database import Base
import uuid
from datetime import datetime
import enum

class DirectionEnum(enum.Enum):
    YES = "YES"
    NO = "NO"

class SignalStatusEnum(enum.Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    IGNORED = "ignored"

class Signal(Base):
    __tablename__ = "signals"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    market_id = Column(String(100), nullable=False)
    sentiment_score = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False)
    direction = Column(Enum(DirectionEnum), nullable=False)
    position_size = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    status = Column(Enum(SignalStatusEnum), default=SignalStatusEnum.PENDING)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    
    # Additional fields for sentiment analysis
    news_sentiment = Column(Float, default=0.0)
    social_sentiment = Column(Float, default=0.0)
    market_sentiment = Column(Float, default=0.0)
    claude_analysis = Column(String(1000), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="signals")
    trades = relationship("Trade", back_populates="signal")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_signal_market_status', 'market_id', 'status'),
        Index('idx_signal_generated_at', 'generated_at'),
        Index('idx_signal_confidence', 'confidence_score'),
    )
