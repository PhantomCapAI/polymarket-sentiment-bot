import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..core.database import AsyncSessionLocal
from ..core.config import settings
from ..models.signal import Signal, SignalStatusEnum, DirectionEnum
from ..models.trade import Trade
from ..services.sentiment_engine import SentimentEngine
from ..services.data_ingestion import DataIngestionService
from ..services.risk_management import RiskManager
from ..utils.exceptions import RiskManagementError

logger = logging.getLogger(__name__)

class SignalGenerator:
    def __init__(self):
        self.sentiment_engine = SentimentEngine()
        self.data_service = DataIngestionService()
        self.risk_manager = RiskManager()
        self.is_running = False
        
    async def start_signal_generation(self):
        """Start continuous signal generation loop"""
        if not self.data_service.redis_client:
            await self.data_service.initialize()
            
        self.is_running = True
        logger.info("Signal generation started")
        
        while self.is_running:
            try:
                await self._generate_signals_for_all_markets()
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                logger.error(f"Signal generation loop error: {str(e)}")
                await asyncio.sleep(60)  # Shorter sleep on error
    
    def stop_signal_generation(self):
        """Stop signal generation"""
        self.is_running = False
        logger.info("Signal generation stopped")
    
    async def _generate_signals_for_all_markets(self):
        """Generate signals for all active markets"""
        try:
            # Get active markets from Redis
            markets = await self.data_service.get_recent_data('markets', 50)
            
            if not markets:
                logger.warning("No market data available for signal generation")
                return
            
            # Process markets in batches to avoid overwhelming APIs
            batch_size = 5
            for i in range(0, len(markets), batch_size):
                batch = markets[i:i + batch_size]
                
                # Process batch concurrently
                tasks = [self._analyze_market_for_signals(market) for market in batch]
                await asyncio.gather(*tasks, return_exceptions=True)
                
                # Rate limiting between batches
                await asyncio.sleep(10)
                
        except Exception as e:
            logger.error(f"Error in signal generation for all markets: {str(e)}")
    
    async def _analyze_market_for_signals(self, market: Dict) -> Optional[str]:
        """Analyze a single market and generate signal if conditions are met"""
        market_id = market.get('market_id')
        question = market.get('question', '')
        
        if not market_id or not question:
            return None
            
        try:
            # Skip if we've recently generated a signal for this market
            if await self._has_recent_signal(market_id):
                return None
            
            # Perform sentiment analysis
            sentiment_result = await self.sentiment_engine.analyze_market_sentiment(market_id, question)
            
            # Check if sentiment meets signal threshold
            signal_data = await self._evaluate_signal_conditions(market, sentiment_result)
            
            if signal_data:
                # Validate against risk management rules
                try:
                    await self.risk_manager.validate_new_position(
                        market_id, signal_data['position_size'], signal_data['direction']
                    )
                    
                    # Create signal
                    signal_id = await self._create_signal(market_id, signal_data, sentiment_result)
                    logger.info(f"Generated signal {signal_id} for market {market_id}")
                    return signal_id
                    
                except RiskManagementError as e:
                    logger.warning(f"Signal blocked by risk management for {market_id}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Error analyzing market {market_id}: {str(e)}")
            
        return None
    
    async def _has_recent_signal(self, market_id: str) -> bool:
        """Check if we've generated a signal for this market recently"""
        async with AsyncSessionLocal() as db:
            cutoff_time = datetime.utcnow() - timedelta(hours=1)
            
            result = await db.execute(
                select(Signal)
                .where(Signal.market_id == market_id)
                .where(Signal.generated_at >= cutoff_time)
                .limit(1)
            )
            
            return result.scalar_one_or_none() is not None
    
    async def _evaluate_signal_conditions(self, market: Dict, sentiment: Dict) -> Optional[Dict]:
        """Evaluate if market conditions warrant a trading signal"""
        overall_score = sentiment.get('overall_score', 0.0)
        confidence = sentiment.get('confidence', 0.0)
        
        # Check minimum confidence threshold
        if confidence < settings.CONFIDENCE_THRESHOLD:
            logger.debug(f"Market {market.get('market_id')} - confidence too low: {confidence}")
            return None
        
        # Get current market price to compare against sentiment
        current_price = await self._get_current_market_price(market)
        if current_price is None:
            return None
        
        # Calculate sentiment-price divergence
        expected_price = self._sentiment_to_price(overall_score)
        divergence = abs(expected_price - current_price)
        
        # Minimum divergence threshold (configurable)
        min_divergence = 0.15  # 15% difference between sentiment and price
        
        if divergence < min_divergence:
            logger.debug(f"Market {market.get('market_id')} - insufficient divergence: {divergence}")
            return None
        
        # Determine direction and position size
        direction = DirectionEnum.YES if expected_price > current_price else DirectionEnum.NO
        position_size = self._calculate_position_size(divergence, confidence)
        
        return {
            'direction': direction,
            'position_size': position_size,
            'expected_price': expected_price,
            'current_price': current_price,
            'divergence': divergence
        }
    
    def _sentiment_to_price(self, sentiment_score: float) -> float:
        """Convert sentiment score (-1 to 1) to expected market price (0 to 1)"""
        # Simple linear mapping with some adjustment
        # Sentiment of 0 maps to price of 0.5
        # Sentiment of 1 maps to price of 0.8 (not 1.0 to account for uncertainty)
        # Sentiment of -1 maps to price of 0.2 (not 0.0 for same reason)
        
        normalized_sentiment = max(-1.0, min(1.0, sentiment_score))
        expected_price = 0.5 + (normalized_sentiment * 0.3)  # Maps to range 0.2-0.8
        
        return max(0.0, min(1.0, expected_price))
    
    async def _get_current_market_price(self, market: Dict) -> Optional[float]:
        """Get current price for the YES outcome of the market"""
        try:
            outcomes = market.get('outcomes', [])
            
            # Find YES outcome
            for outcome in outcomes:
                if outcome.get('title', '').upper() == 'YES':
                    return float(outcome.get('price', 0.5))
            
            # If no explicit YES/NO, use first outcome
            if outcomes:
                return float(outcomes[0].get('price', 0.5))
                
            return None
            
        except (ValueError, TypeError):
            logger.error(f"Invalid price data for market {market.get('market_id')}")
            return None
    
    def _calculate_position_size(self, divergence: float, confidence: float) -> float:
        """Calculate position size based on Kelly criterion and confidence"""
        # Kelly fraction: f = (bp - q) / b
        # Where b = odds, p = probability of winning, q = probability of losing
        
        # Simplified Kelly calculation
        # Higher divergence and confidence = larger position
        base_size = 100.0  # Base position size in USD
        
        # Scale by confidence and divergence
        kelly_multiplier = confidence * min(divergence * 2, 1.0)  # Cap at 1.0
        
        position_size = base_size * kelly_multiplier * settings.KELLY_FRACTION
        
        # Ensure within limits
        return min(position_size, settings.MAX_POSITION_SIZE)
    
    async def _create_signal(self, market_id: str, signal_data: Dict, sentiment_result: Dict) -> str:
        """Create and store a new trading signal"""
        async with AsyncSessionLocal() as db:
            signal = Signal(
                market_id=market_id,
                sentiment_score=sentiment_result.get('overall_score', 0.0),
                confidence_score=sentiment_result.get('confidence', 0.0),
                direction=signal_data['direction'],
                position_size=signal_data['position_size'],
                threshold=settings.CONFIDENCE_THRESHOLD,
                news_sentiment=sentiment_result.get('news_sentiment', 0.0),
                social_sentiment=sentiment_result.get('social_sentiment', 0.0),
                market_sentiment=sentiment_result.get('claude_sentiment', 0.0),
                claude_analysis=sentiment_result.get('claude_analysis', '')[:1000],  # Truncate if too long
                status=SignalStatusEnum.PENDING
            )
            
            db.add(signal)
            await db.commit()
            await db.refresh(signal)
            
            logger.info(
                f"Created signal {signal.id} for market {market_id}: "
                f"direction={signal_data['direction'].value}, "
                f"size={signal_data['position_size']:.2f}, "
                f"confidence={sentiment_result.get('confidence', 0.0):.3f}"
            )
            
            return str(signal.id)
    
    async def get_pending_signals(self) -> List[Signal]:
        """Get all pending signals for execution"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Signal)
                .where(Signal.status == SignalStatusEnum.PENDING)
                .order_by(Signal.generated_at.desc())
            )
            
            return result.scalars().all()
    
    async def manual_signal_analysis(self, market_id: str, question: str) -> Dict:
        """Manual signal analysis for testing/debugging"""
        try:
            sentiment_result = await self.sentiment_engine.analyze_market_sentiment(market_id, question)
            
            # Mock market data for manual analysis
            market = {
                'market_id': market_id,
                'question': question,
                'outcomes': [{'title': 'YES', 'price': 0.5}]  # Default 50/50 market
            }
            
            signal_data = await self._evaluate_signal_conditions(market, sentiment_result)
            
            return {
                'sentiment_analysis': sentiment_result,
                'signal_data': signal_data,
                'would_generate_signal': signal_data is not None
            }
            
        except Exception as e:
            logger.error(f"Manual signal analysis failed: {str(e)}")
            return {'error': str(e)}
