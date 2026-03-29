from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/polymarket_bot"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # Authentication
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Polymarket API
    POLYMARKET_API_KEY: str = ""
    POLYMARKET_SECRET: str = ""
    POLYMARKET_PASSPHRASE: str = ""
    
    # Anthropic API
    ANTHROPIC_API_KEY: str = ""
    
    # News APIs
    NEWS_API_KEY: str = ""
    
    # Social Media APIs
    TWITTER_BEARER_TOKEN: str = ""
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    
    # Trading Parameters
    MAX_POSITION_SIZE: float = 1000.0
    MAX_DAILY_LOSS: float = 2000.0
    MAX_TOTAL_EXPOSURE: float = 5000.0
    CONFIDENCE_THRESHOLD: float = 0.7
    KELLY_FRACTION: float = 0.25
    
    # Environment
    ENVIRONMENT: str = "development"
    
    class Config:
        env_file = ".env"

settings = Settings()
