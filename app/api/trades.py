from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import List, Optional, Dict
from datetime import datetime, timedelta

from ..core.database import get_database
from ..core.auth import get_current_user
from ..models.trade import Trade, TradeStatusEnum
from ..models.user import User
from ..schemas.trade import TradeResponse
from ..services.execution_engine import ExecutionEngine
from ..services.risk_management import RiskManager

router = APIRouter()
execution_engine = ExecutionEngine()
risk_manager = RiskManager()

@router.get("/", response_model=List[TradeResponse])
async def get_trades(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[TradeStatusEnum] = None,
    market_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Get trades with optional filtering"""
    
    query = select(Trade).where(Trade.user_id == current_user.id)
    
    if status:
        query = query.where(Trade.status == status)
    
    if market_id:
        query = query.where(Trade.market_id == market_id)
    
    query = query.order_by(desc(Trade.executed_at)).offset(skip).limit(limit)
    
    result = await db.execute(query)
    trades = result.scalars().all()
    
    return trades

@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Get a specific trade by ID"""
    
    result = await db.execute(
        select(Trade).where(
            Trade.id == trade_id,
            Trade.user_id == current_user.id
        )
    )
    trade = result.scalar_one_or_none()
    
    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade not found"
        )
    
    return trade

@router.post("/{trade_id}/close")
async def close_trade(
    trade_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Close an open trade"""
    
    # Verify trade belongs to user
    result = await db.execute(
        select(Trade).where(
            Trade.id == trade_id,
            Trade.user_id == current_user.id,
            Trade.status == TradeStatusEnum.OPEN
        )
    )
    trade = result.scalar_one_or_none()
    
    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Open trade not found"
        )
    
    try:
        success = await execution_engine.close_position(trade_id)
        if success:
            return {"message": "Trade closed successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to close trade"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error closing trade: {str(e)}"
        )

@router.get("/portfolio/summary")
async def get_portfolio_summary(
    current_user: User = Depends(get_current_user)
):
    """Get portfolio summary"""
    
    try:
        summary = await execution_engine.get_portfolio_summary()
        return summary
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting portfolio summary: {str(e)}"
        )

@router.get("/analytics/performance")
async def get_performance_analytics(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Get performance analytics for specified period"""
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Total trades in period
    total_trades_result = await db.execute(
        select(func.count(Trade.id)).where(
            Trade.user_id == current_user.id,
            Trade.executed_at >= start_date
        )
    )
    total_trades = total_trades_result.scalar() or 0
    
    # Winning trades
    winning_trades_result = await db.execute(
        select(func.count(Trade.id)).where(
            Trade.user_id == current_user.id,
            Trade.executed_at >= start_date,
            Trade.pnl > 0,
            Trade.status == TradeStatusEnum.CLOSED
        )
    )
    winning_trades = winning_trades_result.scalar() or 0
    
    # Total P&L
    total_pnl_result = await db.execute(
        select(func.sum(Trade.pnl)).where(
            Trade.user_id == current_user.id,
            Trade.executed_at >= start_date
        )
    )
    total_pnl = total_pnl_result.scalar() or 0.0
    
    # Calculate win rate
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    return {
        'period_days': days,
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': total_trades - winning_trades,
        'win_rate_percentage': round(win_rate, 2),
        'total_pnl': round(total_pnl, 2),
        'average_pnl_per_trade': round(total_pnl / total_trades, 2) if total_trades > 0 else 0
    }

@router.get("/risk/metrics")
async def get_risk_metrics(
    current_user: User = Depends(get_current_user)
):
    """Get current risk metrics"""
    
    try:
        metrics = await risk_manager.get_risk_metrics()
        return metrics
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting risk metrics: {str(e)}"
        )

@router.post("/stop-loss/check")
async def check_stop_loss(
    current_user: User = Depends(get_current_user)
):
    """Check stop loss conditions and close positions if needed"""
    
    try:
        trades_to_close = await risk_manager.check_stop_loss_conditions()
        
        # Close trades that hit stop loss
        closed_trades = []
        for trade_id in trades_to_close:
            try:
                success = await execution_engine.close_position(trade_id)
                if success:
                    closed_trades.append(trade_id)
            except Exception as e:
                pass  # Log but don't fail entire operation
        
        return {
            'trades_checked': len(trades_to_close),
            'trades_closed': len(closed_trades),
            'closed_trade_ids': closed_trades
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error checking stop loss: {str(e)}"
        )
