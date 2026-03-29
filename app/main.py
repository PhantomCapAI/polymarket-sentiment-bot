from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging

from .core.database import init_database
from .core.config import settings
from .utils.logger import setup_logging
from .api import auth, signals, trades, configurations
from .services.data_ingestion import DataIngestionService
from .services.signal_generator import SignalGenerator
from .services.execution_engine import ExecutionEngine

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Polymarket Sentiment Trading Bot",
    description="AI-powered sentiment analysis and automated trading for Polymarket prediction markets",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["authentication"])
app.include_router(signals.router, prefix="/signals", tags=["signals"])
app.include_router(trades.router, prefix="/trades", tags=["trades"])
app.include_router(configurations.router, prefix="/config", tags=["configuration"])

# Background services
data_service = DataIngestionService()
signal_generator = SignalGenerator()
execution_engine = ExecutionEngine()

@app.on_event("startup")
async def startup_event():
    """Initialize database and start background services"""
    logger.info("Starting Polymarket Trading Bot...")
    
    # Initialize database
    await init_database()
    
    # Start background services
    asyncio.create_task(data_service.start_ingestion())
    asyncio.create_task(signal_generator.start_signal_generation())
    asyncio.create_task(execution_engine.start_execution_loop())
    
    logger.info("All services started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown of services"""
    logger.info("Shutting down services...")
    
    data_service.is_running = False
    signal_generator.stop_signal_generation()
    execution_engine.stop_execution()
    
    await data_service.shutdown()
    
    logger.info("Shutdown complete")

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "message": "Polymarket Sentiment Trading Bot",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "services": {
            "data_ingestion": data_service.is_running,
            "signal_generation": signal_generator.is_running,
            "execution_engine": execution_engine.is_running
        },
        "timestamp": "2024-12-19T10:30:00Z"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
