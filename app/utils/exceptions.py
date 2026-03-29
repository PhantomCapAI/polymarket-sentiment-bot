class TradingBotException(Exception):
    """Base exception for trading bot"""
    pass

class DatabaseError(TradingBotException):
    """Database related errors"""
    pass

class TradingError(TradingBotException):
    """Trading execution errors"""
    pass

class RiskManagementError(TradingBotException):
    """Risk management violations"""
    pass

class DataIngestionError(TradingBotException):
    """Data ingestion errors"""
    pass

class SignalGenerationError(TradingBotException):
    """Signal generation errors"""
    pass

class SentimentAnalysisError(TradingBotException):
    """Sentiment analysis errors"""
    pass

class AuthenticationError(TradingBotException):
    """Authentication errors"""
    pass

class ConfigurationError(TradingBotException):
    """Configuration errors"""
    pass

class ExternalAPIError(TradingBotException):
    """External API errors"""
    pass
