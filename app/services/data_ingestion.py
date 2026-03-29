import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import httpx
import feedparser
import json

from ..core.config import settings
from ..core.database import AsyncSessionLocal
from ..models.news_article import NewsArticle
from ..models.social_post import SocialPost
from ..utils.exceptions import DataIngestionError

logger = logging.getLogger(__name__)

class DataIngestionService:
    def __init__(self):
        self.is_running = False
        self.client = None
    
    async def start_ingestion(self):
        """Start continuous data ingestion"""
        self.is_running = True
        self.client = httpx.AsyncClient(timeout=30.0)
        
        logger.info("Data ingestion service started")
        
        while self.is_running:
            try:
                # Run all ingestion tasks
                await asyncio.gather(
                    self.ingest_news_data(),
                    self.ingest_social_data(),
                    return_exceptions=True
                )
                
                # Wait 15 minutes between cycles
                await asyncio.sleep(900)
                
            except Exception as e:
                logger.error(f"Data ingestion cycle error: {str(e)}")
                await asyncio.sleep(300)  # Wait 5 minutes on error
    
    async def shutdown(self):
        """Shutdown data ingestion service"""
        self.is_running = False
        if self.client:
            await self.client.aclose()
        logger.info("Data ingestion service shutdown")
    
    async def ingest_news_data(self):
        """Ingest news data from various sources"""
        try:
            # RSS feeds to monitor
            rss_feeds = [
                "https://feeds.feedburner.com/techcrunch",
                "https://rss.cnn.com/rss/edition.rss",
                "https://feeds.reuters.com/reuters/businessNews",
                "https://feeds.reuters.com/reuters/technologyNews"
            ]
            
            async with AsyncSessionLocal() as db:
                for feed_url in rss_feeds:
                    try:
                        await self._process_rss_feed(feed_url, db)
                    except Exception as e:
                        logger.error(f"Error processing RSS feed {feed_url}: {str(e)}")
                        continue
                
                await db.commit()
                
        except Exception as e:
            logger.error(f"News data ingestion error: {str(e)}")
            raise DataIngestionError(f"Failed to ingest news data: {str(e)}")
    
    async def _process_rss_feed(self, feed_url: str, db):
        """Process a single RSS feed"""
        try:
            # Get RSS feed
            response = await self.client.get(feed_url)
            response.raise_for_status()
            
            # Parse feed
            feed = feedparser.parse(response.text)
            
            for entry in feed.entries[:10]:  # Process last 10 articles
                # Check if article already exists
                existing = await db.execute(
                    f"SELECT id FROM news_articles WHERE url = '{entry.link}'"
                )
                if existing.fetchone():
                    continue
                
                # Create new article
                article = NewsArticle(
                    title=entry.title,
                    content=entry.get('summary', ''),
                    url=entry.link,
                    source=feed_url,
                    published_at=self._parse_date(entry.get('published')),
                    author=entry.get('author'),
                    category='general'
                )
                
                db.add(article)
                logger.debug(f"Added news article: {article.title}")
                
        except Exception as e:
            logger.error(f"Error processing RSS feed {feed_url}: {str(e)}")
            raise
    
    async def ingest_social_data(self):
        """Ingest social media data"""
        try:
            tasks = []
            
            # Twitter/X data
            if settings.TWITTER_BEARER_TOKEN:
                tasks.append(self._ingest_twitter_data())
            
            # Reddit data
            if settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET:
                tasks.append(self._ingest_reddit_data())
            
            # Execute all social media ingestion tasks
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except Exception as e:
            logger.error(f"Social data ingestion error: {str(e)}")
            raise DataIngestionError(f"Failed to ingest social data: {str(e)}")
    
    async def _ingest_twitter_data(self):
        """Ingest Twitter/X data"""
        try:
            # Keywords to monitor
            keywords = [
                "prediction market", "polymarket", "election", "AI", 
                "crypto", "politics", "economy", "sports betting"
            ]
            
            async with AsyncSessionLocal() as db:
                for keyword in keywords:
                    try:
                        # Mock Twitter API call (replace with actual API)
                        tweets = await self._mock_twitter_search(keyword)
                        
                        for tweet_data in tweets[:5]:  # Process 5 per keyword
                            # Check if post already exists
                            existing = await db.execute(
                                f"SELECT id FROM social_posts WHERE external_id = '{tweet_data['id']}'"
                            )
                            if existing.fetchone():
                                continue
                            
                            post = SocialPost(
                                platform='twitter',
                                external_id=tweet_data['id'],
                                author=tweet_data['author'],
                                content=tweet_data['text'],
                                url=tweet_data['url'],
                                posted_at=tweet_data['created_at'],
                                engagement_score=tweet_data.get('retweet_count', 0) + 
                                               tweet_data.get('like_count', 0)
                            )
                            
                            db.add(post)
                            logger.debug(f"Added Twitter post: {post.external_id}")
                            
                    except Exception as e:
                        logger.error(f"Error ingesting Twitter data for '{keyword}': {str(e)}")
                        continue
                
                await db.commit()
                
        except Exception as e:
            logger.error(f"Twitter ingestion error: {str(e)}")
            raise
    
    async def _ingest_reddit_data(self):
        """Ingest Reddit data"""
        try:
            # Subreddits to monitor
            subreddits = [
                'PredictionMarkets', 'betting', 'politics', 'technology',
                'MachineLearning', 'cryptocurrency', 'wallstreetbets'
            ]
            
            async with AsyncSessionLocal() as db:
                for subreddit in subreddits:
                    try:
                        # Mock Reddit API call (replace with actual API)
                        posts = await self._mock_reddit_search(subreddit)
                        
                        for post_data in posts[:3]:  # Process 3 per subreddit
                            # Check if post already exists
                            existing = await db.execute(
                                f"SELECT id FROM social_posts WHERE external_id = '{post_data['id']}'"
                            )
                            if existing.fetchone():
                                continue
                            
                            post = SocialPost(
                                platform='reddit',
                                external_id=post_data['id'],
                                author=post_data['author'],
                                content=post_data['title'] + '\n\n' + post_data.get('selftext', ''),
                                url=post_data['url'],
                                posted_at=post_data['created_utc'],
                                engagement_score=post_data.get('score', 0)
                            )
                            
                            db.add(post)
                            logger.debug(f"Added Reddit post: {post.external_id}")
                            
                    except Exception as e:
                        logger.error(f"Error ingesting Reddit data from r/{subreddit}: {str(e)}")
                        continue
                
                await db.commit()
                
        except Exception as e:
            logger.error(f"Reddit ingestion error: {str(e)}")
            raise
    
    async def _mock_twitter_search(self, keyword: str) -> List[Dict]:
        """Mock Twitter API search - replace with actual API"""
        return [
            {
                'id': f'tweet_{keyword}_{i}',
                'text': f'Mock tweet about {keyword} - this is interesting content',
                'author': f'user_{i}',
                'url': f'https://twitter.com/user_{i}/status/123456789{i}',
                'created_at': datetime.utcnow() - timedelta(hours=i),
                'retweet_count': i * 10,
                'like_count': i * 25
            }
            for i in range(1, 6)
        ]
    
    async def _mock_reddit_search(self, subreddit: str) -> List[Dict]:
        """Mock Reddit API search - replace with actual API"""
        return [
            {
                'id': f'reddit_{subreddit}_{i}',
                'title': f'Mock post from r/{subreddit} #{i}',
                'selftext': f'This is mock content from r/{subreddit}',
                'author': f'redditor_{i}',
                'url': f'https://reddit.com/r/{subreddit}/comments/abc123/',
                'created_utc': datetime.utcnow() - timedelta(hours=i*2),
                'score': i * 50
            }
            for i in range(1, 4)
        ]
    
    def _parse_date(self, date_str: Optional[str]) -> datetime:
        """Parse date string to datetime"""
        if not date_str:
            return datetime.utcnow()
        
        try:
            from dateutil import parser
            return parser.parse(date_str)
        except:
            return datetime.utcnow()
    
    async def get_recent_data_summary(self) -> Dict:
        """Get summary of recently ingested data"""
        async with AsyncSessionLocal() as db:
            from sqlalchemy import func
            
            # Count articles from last 24 hours
            day_ago = datetime.utcnow() - timedelta(days=1)
            
            articles_result = await db.execute(
                f"SELECT COUNT(*) FROM news_articles WHERE created_at >= '{day_ago}'"
            )
            articles_count = articles_result.scalar()
            
            posts_result = await db.execute(
                f"SELECT COUNT(*) FROM social_posts WHERE created_at >= '{day_ago}'"
            )
            posts_count = posts_result.scalar()
            
            return {
                'articles_last_24h': articles_count or 0,
                'social_posts_last_24h': posts_count or 0,
                'last_update': datetime.utcnow().isoformat(),
                'service_status': 'running' if self.is_running else 'stopped'
            }
