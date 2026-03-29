import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..core.database import AsyncSessionLocal
from ..core.config import settings
from ..models.signal import Signal, SignalStatusEnum
from ..models.trade import Trade, TradeStatusEnum, OrderTypeEnum, DirectionEnum
from ..utils.exceptions import TradingError
from ..utils.circuit_breaker import polymarket_circuit_breaker

logger = logging.getLogger(__name__)

class ExecutionEngine:
    def __init__(self):
        self.clob_client = None
        self.is_running = False
        
    async def initialize(self):
        """Initialize Polymarket CLOB client"""
        try:
            self.clob_client = ClobClient(
                host="https://clob.polymarket.com",
                key=settings.POLYMARKET_API_KEY,
                secret=settings.POLYMARKET_SECRET,
                passphrase=settings.POLYMARKET_PASSPHRASE,
                chain_id=POLYGON,
            )
            logger.info("Polymarket CLOB client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {str(e)}")
            raise TradingError(f"CLOB client initialization failed: {str(e)}")
    
    async def start_execution_loop(self):
        """Start continuous execution loop for pending signals"""
        if not self.clob_client:
            await self.initialize()
            
        self.is_running = True
        logger.info("Execution engine started")
        
        while self.is_running:
            try:
                await self._execute_pending_signals()
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Execution loop error: {str(e)}")
                await asyncio.sleep(60)
    
    def stop_execution(self):
        """Stop execution loop"""
        self.is_running = False
        logger.info("Execution engine stopped")
    
    async def _execute_pending_signals(self):
        """Execute all pending signals"""
        async with AsyncSessionLocal() as db:
            # Get pending signals
            result = await db.execute(
                select(Signal)
                .where(Signal.status == SignalStatusEnum.PENDING)
                .order_by(Signal.generated_at.asc())
                .limit(10)  # Process up to 10 at a time
            )
            
            pending_signals = result.scalars().all()
            
            for signal in pending_signals:
                try:
                    await self._execute_signal(signal, db)
                except Exception as e:
                    logger.error(f"Failed to execute signal {signal.id}: {str(e)}")
                    # Mark signal as failed
                    signal.status = SignalStatusEnum.IGNORED
                    await db.commit()
    
    async def _execute_signal(self, signal: Signal, db: AsyncSession):
        """Execute a single trading signal"""
        try:
            # Get market information
            market_info = await self._get_market_info(signal.market_id)
            if not market_info:
                raise TradingError(f"Market {signal.market_id} not found")
            
            # Determine outcome token ID based on direction
            outcome_id = self._get_outcome_id(market_info, signal.direction)
            if not outcome_id:
                raise TradingError(f"Could not determine outcome ID for direction {signal.direction}")
            
            # Get current price
            current_price = await self._get_current_price(outcome_id)
            if current_price is None:
                raise TradingError(f"Could not get current price for outcome {outcome_id}")
            
            # Create order
            order_result = await polymarket_circuit_breaker.call(
                self._place_order,
                outcome_id,
                signal.position_size,
                current_price,
                signal.direction
            )
            
            if order_result:
                # Create trade record
                trade = Trade(
                    market_id=signal.market_id,
                    signal_id=signal.id,
                    order_type=OrderTypeEnum.MARKET,
                    position_size=signal.position_size,
                    direction=signal.direction,
                    entry_price=current_price,
                    status=TradeStatusEnum.OPEN,
                    order_id=order_result.get('id'),
                    user_id=signal.user_id
                )
                
                db.add(trade)
                
                # Update signal status
                signal.status = SignalStatusEnum.EXECUTED
                
                await db.commit()
                
                logger.info(
                    f"Successfully executed signal {signal.id}: "
                    f"trade_id={trade.id}, order_id={order_result.get('id')}"
                )
            else:
                signal.status = SignalStatusEnum.IGNORED
                await db.commit()
                
        except Exception as e:
            logger.error(f"Error executing signal {signal.id}: {str(e)}")
            raise
    
    async def _get_market_info(self, market_id: str) -> Optional[Dict]:
        """Get market information from Polymarket API"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"https://clob.polymarket.com/markets/{market_id}")
                if resp.status_code == 200:
                    return resp.json()
                logger.warning(f"Market {market_id} returned status {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting market info for {market_id}: {str(e)}")
            return None
    
    def _get_outcome_id(self, market_info: Dict, direction: DirectionEnum) -> Optional[str]:
        """Get outcome token ID based on direction"""
        tokens = market_info.get('tokens', [])

        for token in tokens:
            outcome = token.get('outcome', '').upper()
            if direction == DirectionEnum.YES and outcome == 'YES':
                return token.get('token_id')
            elif direction == DirectionEnum.NO and outcome == 'NO':
                return token.get('token_id')

        # Fallback: first token = YES, second = NO
        if len(tokens) >= 2:
            idx = 0 if direction == DirectionEnum.YES else 1
            return tokens[idx].get('token_id')

        return None
    
    async def _get_current_price(self, outcome_id: str) -> Optional[float]:
        """Get current price for outcome token from Polymarket CLOB orderbook"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://clob.polymarket.com/price",
                    params={"token_id": outcome_id, "side": "buy"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return float(data.get("price", 0))
            # Fallback: try midpoint from orderbook
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://clob.polymarket.com/book",
                    params={"token_id": outcome_id},
                )
                if resp.status_code == 200:
                    book = resp.json()
                    best_bid = float(book.get("bids", [{}])[0].get("price", 0)) if book.get("bids") else 0
                    best_ask = float(book.get("asks", [{}])[0].get("price", 0)) if book.get("asks") else 0
                    if best_bid > 0 and best_ask > 0:
                        return (best_bid + best_ask) / 2
                    return best_bid or best_ask or None
            return None
        except Exception as e:
            logger.error(f"Error getting price for outcome {outcome_id}: {str(e)}")
            return None
    
    async def _place_order(self, outcome_id: str, size: float, price: float, direction: DirectionEnum) -> Optional[Dict]:
        """Place order on Polymarket CLOB using py-clob-client"""
        try:
            if not self.clob_client:
                raise TradingError("CLOB client not initialized")

            from py_clob_client.order_builder.constants import BUY, SELL

            # Buy YES tokens = bullish, Buy NO tokens = bearish
            side = BUY

            order_args = {
                "token_id": outcome_id,
                "price": round(price, 2),
                "size": round(size / price, 2),  # Convert USD to shares
                "side": side,
            }

            # Create and sign the order
            signed_order = self.clob_client.create_and_sign_order(order_args)
            result = self.clob_client.post_order(signed_order)

            if result and result.get("success"):
                order_id = result.get("orderID", result.get("id", f"order_{datetime.utcnow().timestamp()}"))
                logger.info(f"Order placed: {order_id} | {outcome_id} | {size} USD @ {price}")
                return {"id": order_id, "status": "placed", **order_args}
            else:
                error_msg = result.get("errorMsg", "Unknown error") if result else "No response"
                logger.error(f"Order rejected: {error_msg}")
                return None

        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            raise TradingError(f"Order placement failed: {str(e)}")
    
    async def close_position(self, trade_id: str) -> bool:
        """Close an open position"""
        async with AsyncSessionLocal() as db:
            try:
                # Get trade
                result = await db.execute(
                    select(Trade).where(Trade.id == trade_id)
                )
                trade = result.scalar_one_or_none()
                
                if not trade or trade.status != TradeStatusEnum.OPEN:
                    raise TradingError(f"Trade {trade_id} not found or not open")
                
                # Get current price
                market_info = await self._get_market_info(trade.market_id)
                if not market_info:
                    raise TradingError(f"Market {trade.market_id} not found")
                
                outcome_id = self._get_outcome_id(market_info, trade.direction)
                current_price = await self._get_current_price(outcome_id)
                
                if current_price is None:
                    raise TradingError("Could not get current price for closing")
                
                # Calculate P&L
                if trade.direction == DirectionEnum.YES:
                    pnl = (current_price - trade.entry_price) * trade.position_size
                else:
                    pnl = (trade.entry_price - current_price) * trade.position_size
                
                # Place closing order (opposite direction)
                closing_direction = DirectionEnum.NO if trade.direction == DirectionEnum.YES else DirectionEnum.YES
                
                close_order = await polymarket_circuit_breaker.call(
                    self._place_order,
                    outcome_id,
                    trade.position_size,
                    current_price,
                    closing_direction
                )
                
                if close_order:
                    # Update trade
                    trade.exit_price = current_price
                    trade.pnl = pnl
                    trade.status = TradeStatusEnum.CLOSED
                    
                    await db.commit()
                    
                    logger.info(f"Closed trade {trade_id}: P&L = {pnl:.2f}")
                    return True
                
                return False
                
            except Exception as e:
                logger.error(f"Error closing trade {trade_id}: {str(e)}")
                raise TradingError(f"Failed to close position: {str(e)}")
    
    async def get_portfolio_summary(self) -> Dict:
        """Get current portfolio summary"""
        async with AsyncSessionLocal() as db:
            # Open positions
            open_result = await db.execute(
                select(Trade).where(Trade.status == TradeStatusEnum.OPEN)
            )
            open_trades = open_result.scalars().all()
            
            # Calculate unrealized P&L
            total_unrealized_pnl = 0.0
            for trade in open_trades:
                market_info = await self._get_market_info(trade.market_id)
                outcome_id = self._get_outcome_id(market_info, trade.direction) if market_info else None
                current_price = await self._get_current_price(outcome_id) if outcome_id else None
                if current_price is None:
                    current_price = trade.entry_price  # Fallback: assume no change
                if trade.direction == DirectionEnum.YES:
                    unrealized_pnl = (current_price - trade.entry_price) * trade.position_size
                else:
                    unrealized_pnl = (trade.entry_price - current_price) * trade.position_size
                total_unrealized_pnl += unrealized_pnl
            
            # Realized P&L
            from sqlalchemy import func
            realized_result = await db.execute(
                select(func.sum(Trade.pnl))
                .where(Trade.status == TradeStatusEnum.CLOSED)
            )
            total_realized_pnl = realized_result.scalar() or 0.0
            
            return {
                'open_positions': len(open_trades),
                'total_unrealized_pnl': total_unrealized_pnl,
                'total_realized_pnl': total_realized_pnl,
                'total_pnl': total_unrealized_pnl + total_realized_pnl,
                'open_trades': [
                    {
                        'id': str(trade.id),
                        'market_id': trade.market_id,
                        'direction': trade.direction.value,
                        'position_size': trade.position_size,
                        'entry_price': trade.entry_price,
                        'executed_at': trade.executed_at.isoformat()
                    }
                    for trade in open_trades
                ]
            }
