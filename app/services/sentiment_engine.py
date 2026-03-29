import asyncio
import anthropic
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import re

from ..core.config import settings
from ..utils.circuit_breaker import claude_circuit_breaker
from ..utils.exceptions import SentimentAnalysisError, ExternalAPIError
from .data_ingestion import DataIngestionService

logger = logging.getLogger(__name__)

class SentimentEngine:
    def __init__(self):
        self.anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.data_service = DataIngestionService()
        self.claude_call_count = 0
        self.last_reset_time = datetime.utcnow()
        
    async def analyze_market_sentiment(self, market_id: str, question: str) -> Dict[str, Any]:
        """Analyze sentiment for a specific market"""
        try:
            # Get relevant data
            news_data = await self.data_service.get_recent_data('news', 20)
            social_data = await self.data_service.get_recent_data('social', 30)
            
            # Filter data relevant to the market
            relevant_data = self._filter_relevant_data(question, news_data + social_data)
            
            if not relevant_data:
                logger.warning(f"No relevant data found for market: {question}")
                return self._default_sentiment_result()
            
            # Fast sentiment analysis (local processing)
            fast_sentiment = await self._fast_sentiment_analysis(relevant_data)
            
            # Deep analysis with Claude (rate limited)
            claude_sentiment = await self._claude_sentiment_analysis(question, relevant_data)
            
            # Combine sentiments with weights
            combined_sentiment = self._combine_sentiment_scores(fast_sentiment, claude_sentiment)
            
            logger.info(f"Sentiment analysis completed for market {market_id}: {combined_sentiment['overall_score']}")
            
            return combined_sentiment
            
        except Exception as e:
            logger.error(f"Sentiment analysis failed for market {market_id}: {str(e)}")
            raise SentimentAnalysisError(f"Failed to analyze sentiment: {str(e)}")
    
    def _filter_relevant_data(self, question: str, data: List[Dict]) -> List[Dict]:
        """Filter data relevant to the market question"""
        # Extract keywords from the question
        keywords = self._extract_keywords(question)
        relevant_data = []
        
        for item in data:
            text_content = f"{item.get('title', '')} {item.get('description', '')} {item.get('selftext', '')}"
            
            # Check if any keywords appear in the content
            if any(keyword.lower() in text_content.lower() for keyword in keywords):
                relevant_data.append(item)
                
        return relevant_data[:10]  # Limit to top 10 most relevant
    
    def _extract_keywords(self, question: str) -> List[str]:
        """Extract relevant keywords from market question"""
        # Remove common stop words and extract meaningful terms
        stop_words = {'will', 'be', 'the', 'in', 'on', 'at', 'to', 'for', 'of', 'by', 'with', 'a', 'an', 'and', 'or', 'but'}
        
        # Clean and tokenize
        cleaned = re.sub(r'[^\w\s]', ' ', question.lower())
        words = [word for word in cleaned.split() if word not in stop_words and len(word) > 2]
        
        return words[:5]  # Top 5 keywords
    
    async def _fast_sentiment_analysis(self, data: List[Dict]) -> Dict[str, float]:
        """Fast sentiment analysis using simple keyword matching"""
        positive_keywords = ['positive', 'good', 'great', 'success', 'win', 'bullish', 'up', 'rise', 'gain', 'strong']
        negative_keywords = ['negative', 'bad', 'fail', 'loss', 'bearish', 'down', 'fall', 'drop', 'weak', 'decline']
        
        scores = []
        
        for item in data:
            text = f"{item.get('title', '')} {item.get('description', '')} {item.get('selftext', '')}".lower()
            
            positive_count = sum(1 for word in positive_keywords if word in text)
            negative_count = sum(1 for word in negative_keywords if word in text)
            
            # Simple scoring: normalize between -1 and 1
            if positive_count + negative_count > 0:
                score = (positive_count - negative_count) / (positive_count + negative_count)
            else:
                score = 0.0
                
            # Weight by source credibility and recency
            weight = self._calculate_source_weight(item)
            scores.append(score * weight)
        
        if scores:
            return {
                'news_sentiment': sum(s for s in scores if s != 0) / max(len([s for s in scores if s != 0]), 1),
                'social_sentiment': 0.0,  # Separate social from news
                'confidence': min(len(scores) / 10.0, 1.0)  # More data = higher confidence
            }
        else:
            return {'news_sentiment': 0.0, 'social_sentiment': 0.0, 'confidence': 0.0}
    
    def _calculate_source_weight(self, item: Dict) -> float:
        """Calculate weight based on source credibility and recency"""
        base_weight = 1.0
        
        # Source credibility
        if item.get('type') == 'news':
            source = item.get('source', '')
            if 'reuters' in source.lower():
                base_weight *= 1.5
            elif 'bloomberg' in source.lower():
                base_weight *= 1.4
            elif 'cnn' in source.lower():
                base_weight *= 1.2
                
        elif item.get('type') == 'reddit':
            # Weight by score and comments
            score = item.get('score', 0)
            comments = item.get('num_comments', 0)
            base_weight *= min(1 + (score + comments) / 100, 2.0)
        
        # Recency weight (newer content weighted higher)
        try:
            timestamp_str = item.get('timestamp', '')
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                hours_old = (datetime.utcnow() - timestamp.replace(tzinfo=None)).total_seconds() / 3600
                recency_weight = max(0.5, 1.0 - (hours_old / 24))  # Decay over 24 hours
                base_weight *= recency_weight
        except:
            pass  # Use base weight if timestamp parsing fails
            
        return base_weight
    
    async def _claude_sentiment_analysis(self, question: str, data: List[Dict]) -> Dict[str, Any]:
        """Deep sentiment analysis using Claude API with rate limiting"""
        if not self._can_make_claude_call():
            logger.info("Claude rate limit reached, using cached/default analysis")
            return {'claude_sentiment': 0.0, 'analysis': 'Rate limited', 'confidence': 0.3}
        
        try:
            # Prepare context for Claude
            context = self._prepare_claude_context(question, data)
            
            prompt = f"""
            Analyze the sentiment for this prediction market question: "{question}"
            
            Based on the following recent news and social media data:
            {context}
            
            Provide a JSON response with:
            1. sentiment_score: float between -1 (very negative) and 1 (very positive)
            2. confidence: float between 0 and 1 
            3. key_factors: list of main factors influencing the sentiment
            4. analysis: brief explanation of your reasoning
            
            Focus on how this information affects the likelihood of the prediction being correct.
            """
            
            result = await claude_circuit_breaker.call(
                self._make_claude_api_call, prompt
            )
            
            self.claude_call_count += 1
            return self._parse_claude_response(result)
            
        except Exception as e:
            logger.error(f"Claude sentiment analysis failed: {str(e)}")
            return {'claude_sentiment': 0.0, 'analysis': f'Error: {str(e)}', 'confidence': 0.0}
    
    def _can_make_claude_call(self) -> bool:
        """Check if we can make a Claude API call based on rate limits"""
        current_time = datetime.utcnow()
        
        # Reset counter every hour
        if (current_time - self.last_reset_time).total_seconds() >= 3600:
            self.claude_call_count = 0
            self.last_reset_time = current_time
            
        max_calls = getattr(settings, 'CLAUDE_MAX_CALLS_PER_HOUR', 10)
        return self.claude_call_count < max_calls
    
    def _prepare_claude_context(self, question: str, data: List[Dict]) -> str:
        """Prepare context string for Claude analysis"""
        context_parts = []
        
        for i, item in enumerate(data[:5]):  # Limit to avoid token limits
            if item.get('type') == 'news':
                context_parts.append(f"News {i+1}: {item.get('title', '')} - {item.get('description', '')[:200]}")
            elif item.get('type') == 'reddit':
                context_parts.append(f"Reddit {i+1}: {item.get('title', '')} (Score: {item.get('score', 0)})")
                
        return "\n".join(context_parts)
    
    async def _make_claude_api_call(self, prompt: str) -> str:
        """Make actual API call to Claude"""
        try:
            message = await self.anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except Exception as e:
            raise ExternalAPIError(f"Claude API call failed: {str(e)}")
    
    def _parse_claude_response(self, response: str) -> Dict[str, Any]:
        """Parse Claude's JSON response"""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                return {
                    'claude_sentiment': parsed.get('sentiment_score', 0.0),
                    'analysis': parsed.get('analysis', ''),
                    'confidence': parsed.get('confidence', 0.5),
                    'key_factors': parsed.get('key_factors', [])
                }
        except:
            pass
            
        # Fallback parsing if JSON fails
        return {
            'claude_sentiment': 0.0,
            'analysis': response[:500],  # Truncate long responses
            'confidence': 0.3
        }
    
    def _combine_sentiment_scores(self, fast: Dict[str, float], claude: Dict[str, Any]) -> Dict[str, Any]:
        """Combine fast and Claude sentiment analysis results"""
        # Weights for different components
        fast_weight = 0.4
        claude_weight = 0.6
        
        # Calculate overall sentiment score
        overall_score = (
            fast.get('news_sentiment', 0.0) * fast_weight +
            claude.get('claude_sentiment', 0.0) * claude_weight
        )
        
        # Calculate overall confidence
        overall_confidence = (
            fast.get('confidence', 0.0) * fast_weight +
            claude.get('confidence', 0.0) * claude_weight
        )
        
        return {
            'overall_score': max(-1.0, min(1.0, overall_score)),  # Clamp between -1 and 1
            'confidence': max(0.0, min(1.0, overall_confidence)),
            'news_sentiment': fast.get('news_sentiment', 0.0),
            'social_sentiment': fast.get('social_sentiment', 0.0),
            'claude_sentiment': claude.get('claude_sentiment', 0.0),
            'claude_analysis': claude.get('analysis', ''),
            'key_factors': claude.get('key_factors', [])
        }
    
    def _default_sentiment_result(self) -> Dict[str, Any]:
        """Return default sentiment result when no data is available"""
        return {
            'overall_score': 0.0,
            'confidence': 0.0,
            'news_sentiment': 0.0,
            'social_sentiment': 0.0,
            'claude_sentiment': 0.0,
            'claude_analysis': 'No relevant data found',
            'key_factors': []
        }
