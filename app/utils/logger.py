import logging
import sys
from logging.handlers import RotatingFileHandler
import os

def setup_logging():
    """Setup logging configuration"""
    
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Root logger configuration
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            # Console handler
            logging.StreamHandler(sys.stdout),
            # File handler with rotation
            RotatingFileHandler(
                "logs/trading_bot.log",
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
        ]
    )
    
    # Set specific loggers to appropriate levels
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    
    # Trading bot specific loggers
    logging.getLogger("app.services.signal_generator").setLevel(logging.INFO)
    logging.getLogger("app.services.execution_engine").setLevel(logging.INFO)
    logging.getLogger("app.services.risk_management").setLevel(logging.INFO)
    logging.getLogger("app.services.data_ingestion").setLevel(logging.INFO)
    
    logger = logging.getLogger(__name__)
    logger.info("Logging configuration initialized")
