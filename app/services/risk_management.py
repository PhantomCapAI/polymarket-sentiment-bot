import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..core.database import AsyncSessionLocal
from ..core.config import settings
from ..models.trade import Trade, TradeStatusEnum
from ..models.signal import DirectionEnum
from ..utils.exceptions import RiskManagementError

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self):
        pass
    
    async def validate_new_position(self, market_id: str, position_size: float, direction: DirectionEnum):
        """Validate if new position is within risk limits"""
        
        # Check individual position size limit
        if position_size > settings.MAX_POSITION_SIZE:
            raise RiskManagementError(
                f"Position size {position_size} exceeds maximum allowed {settings.MAX_POSITION_SIZE}"
            )
        
        # Check if adding this position would exceed total exposure
        current_exposure = await self._get_total_exposure()
        if current_exposure + position_size > settings.MAX_TOTAL_EXPOSURE:
            raise RiskManagementError(
                f"New position would exceed total exposure limit. "
                f"Current: {current_exposure}, New: {position_size}, Limit: {settings.MAX_TOTAL_EXPOSURE}"
            )
        
        # Check daily loss limit
        daily_pnl = await self._get_daily_pnl()
        if daily_pnl < -settings.MAX_DAILY_LOSS:
            raise RiskManagementError(
                f"Daily loss limit exceeded. Current P&L: {daily_pnl}, Limit: {-settings.MAX_DAILY_LOSS}"
            )
        
        # Check market concentration (max 3 positions per market)
        market_positions = await self._get_market_position_count(market_id)
        if market_positions >= 3:
            raise RiskManagementError(
                f"Too many open positions in market {market_id}. Current: {market_positions}, Max: 3"
            )
        
        logger.info(f"Risk validation passed for position: {market_id}, {position_size}, {direction.value}")
    
    async def _get_total_exposure(self) -> float:
        """Get current total exposure across all open positions"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(func.sum(Trade.position_size))
                .where(Trade.status == TradeStatusEnum.OPEN)
            )
            
            total = result.scalar()
            return total if total else 0.0
    
    async def _get_daily_pnl(self) -> float:
        """Get today's realized and unrealized P&L"""
        async with AsyncSessionLocal() as db:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Get closed trades P&L for today
            result = await db.execute(
                select(func.sum(Trade.pnl))
                .where(Trade.status == TradeStatusEnum.CLOSED)
                .where(Trade.executed_at >= today_start)
            )
            
            closed_pnl = result.scalar()
            return closed_pnl if closed_pnl else 0.0
    
    async def _get_market_position_count(self, market_id: str) -> int:
        """Get number of open positions in specific market"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(func.count(Trade.id))
                .where(Trade.market_id == market_id)
                .where(Trade.status == TradeStatusEnum.OPEN)
            )
            
            return result.scalar() or 0
    
    async def check_stop_loss_conditions(self) -> List[str]:
        """Check all open positions for stop loss conditions"""
        trade_ids_to_close = []
        
        async with AsyncSessionLocal() as db:
            # Get all open trades
            result = await db.execute(
                select(Trade).where(Trade.status == TradeStatusEnum.OPEN)
            )
            open_trades = result.scalars().all()
            
            for trade in open_trades:
                # Get current market price (mock for now)
                current_price = await self._get_current_price(trade.market_id)
                if current_price is None:
                    continue
                
                # Calculate current P&L
                if trade.direction == DirectionEnum.YES:
                    current_pnl = (current_price - trade.entry_price) * trade.position_size
                else:
                    current_pnl = (trade.entry_price - current_price) * trade.position_size
                
                # Stop loss at -20% of position size
                stop_loss_threshold = -0.2 * trade.position_size
                
                if current_pnl <= stop_loss_threshold:
                    trade_ids_to_close.append(str(trade.id))
                    logger.warning(
                        f"Stop loss triggered for trade {trade.id}: "
                        f"P&L {current_pnl:.2f} <= threshold {stop_loss_threshold:.2f}"
                    )
        
        return trade_ids_to_close
    
    async def _get_current_price(self, market_id: str) -> Optional[float]:
        """Get current market price from Polymarket API"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                # Get market info to find token IDs
                resp = await client.get(f"https://clob.polymarket.com/markets/{market_id}")
                if resp.status_code != 200:
                    return None
                market = resp.json()
                tokens = market.get("tokens", [])
                if not tokens:
                    return None
                # Get YES token price
                token_id = tokens[0].get("token_id")
                price_resp = await client.get(
                    "https://clob.polymarket.com/price",
                    params={"token_id": token_id, "side": "buy"},
                )
                if price_resp.status_code == 200:
                    return float(price_resp.json().get("price", 0))
                return None
        except Exception as e:
            logger.error(f"Error fetching price for market {market_id}: {str(e)}")
            return None
    
    async def get_risk_metrics(self) -> Dict[str, float]:
        """Get current risk metrics dashboard"""
        async with AsyncSessionLocal() as db:
            # Total exposure
            exposure_result = await db.execute(
                select(func.sum(Trade.position_size))
                .where(Trade.status == TradeStatusEnum.OPEN)
            )
            total_exposure = exposure_result.scalar() or 0.0
            
            # Number of open positions
            count_result = await db.execute(
                select(func.count(Trade.id))
                .where(Trade.status == TradeStatusEnum.OPEN)
            )
            open_positions = count_result.scalar() or 0
            
            # Daily P&L calculation
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            daily_pnl_result = await db.execute(
                select(func.sum(Trade.pnl))
                .where(Trade.executed_at >= today_start)
            )
            daily_pnl = daily_pnl_result.scalar() or 0.0
            
            # Total P&L (all time)
            total_pnl_result = await db.execute(
                select(func.sum(Trade.pnl))
            )
            total_pnl = total_pnl_result.scalar() or 0.0
            
            # Utilization percentages
            exposure_utilization = (total_exposure / settings.MAX_TOTAL_EXPOSURE) * 100 if settings.MAX_TOTAL_EXPOSURE > 0 else 0
            daily_loss_utilization = abs(daily_pnl / settings.MAX_DAILY_LOSS) * 100 if daily_pnl < 0 and settings.MAX_DAILY_LOSS > 0 else 0
            
            return {
                'total_exposure': total_exposure,
                'max_exposure': settings.MAX_TOTAL_EXPOSURE,
                'exposure_utilization_pct': exposure_utilization,
                'open_positions': open_positions,
                'daily_pnl': daily_pnl,
                'max_daily_loss': settings.MAX_DAILY_LOSS,
                'daily_loss_utilization_pct': daily_loss_utilization,
                'total_pnl': total_pnl
            }
