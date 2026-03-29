from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
from datetime import datetime, timedelta

from ..core.database import get_database
from ..core.auth import get_current_user
from ..models.signal import Signal, SignalStatusEnum
from ..models.user import User
from ..schemas.signal import SignalCreate, SignalResponse
from ..services.signal_generator import SignalGenerator

router = APIRouter()
signal_generator = SignalGenerator()

@router.post("/", response_model=SignalResponse, status_code=status.HTTP_201_CREATED)
async def create_signal(
    signal_data: SignalCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Create a new trading signal"""
    
    signal = Signal(
        **signal_data.dict(),
        user_id=current_user.id
    )
    
    db.add(signal)
    await db.commit()
    await db.refresh(signal)
    
    return signal

@router.get("/", response_model=List[SignalResponse])
async def get_signals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[SignalStatusEnum] = None,
    market_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Get signals with optional filtering"""
    
    query = select(Signal).where(Signal.user_id == current_user.id)
    
    if status:
        query = query.where(Signal.status == status)
    
    if market_id:
        query = query.where(Signal.market_id == market_id)
    
    query = query.order_by(desc(Signal.generated_at)).offset(skip).limit(limit)
    
    result = await db.execute(query)
    signals = result.scalars().all()
    
    return signals

@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(
    signal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Get a specific signal by ID"""
    
    result = await db.execute(
        select(Signal).where(
            Signal.id == signal_id,
            Signal.user_id == current_user.id
        )
    )
    signal = result.scalar_one_or_none()
    
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal not found"
        )
    
    return signal

@router.post("/analyze")
async def manual_signal_analysis(
    market_id: str,
    question: str,
    current_user: User = Depends(get_current_user)
):
    """Manually analyze a market for signal generation"""
    
    try:
        result = await signal_generator.manual_signal_analysis(market_id, question)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}"
        )

@router.get("/pending/count")
async def get_pending_signals_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Get count of pending signals"""
    
    from sqlalchemy import func
    
    result = await db.execute(
        select(func.count(Signal.id)).where(
            Signal.status == SignalStatusEnum.PENDING,
            Signal.user_id == current_user.id
        )
    )
    count = result.scalar()
    
    return {"pending_count": count or 0}

@router.put("/{signal_id}/status")
async def update_signal_status(
    signal_id: str,
    new_status: SignalStatusEnum,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Update signal status"""
    
    result = await db.execute(
        select(Signal).where(
            Signal.id == signal_id,
            Signal.user_id == current_user.id
        )
    )
    signal = result.scalar_one_or_none()
    
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal not found"
        )
    
    signal.status = new_status
    await db.commit()
    
    return {"message": f"Signal status updated to {new_status}"}
