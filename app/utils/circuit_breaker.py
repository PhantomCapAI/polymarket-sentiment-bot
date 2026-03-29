import asyncio
import time
import logging
from typing import Callable, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreakerError(Exception):
    pass

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitState.CLOSED
        
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        
        # Check if circuit should transition from OPEN to HALF_OPEN
        if (self.state == CircuitState.OPEN and 
            self.last_failure_time and 
            time.time() - self.last_failure_time >= self.timeout):
            
            self.state = CircuitState.HALF_OPEN
            logger.info("Circuit breaker transitioning to HALF_OPEN")
        
        # If circuit is OPEN, reject the call
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerError("Circuit breaker is OPEN")
        
        try:
            # Execute the function
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # Success - reset failure count and close circuit
            self._on_success()
            return result
            
        except Exception as e:
            # Failure - increment count and potentially open circuit
            self._on_failure()
            raise e
    
    def _on_success(self):
        """Handle successful call"""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        logger.debug("Circuit breaker: Success - circuit CLOSED")
    
    def _on_failure(self):
        """Handle failed call"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker: {self.failure_count} failures - circuit OPEN for {self.timeout}s"
            )
        else:
            logger.debug(f"Circuit breaker: Failure {self.failure_count}/{self.failure_threshold}")
    
    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN
    
    @property 
    def is_half_open(self) -> bool:
        return self.state == CircuitState.HALF_OPEN
    
    def reset(self):
        """Manually reset circuit breaker"""
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
        logger.info("Circuit breaker manually reset")

# Create instances for external API calls
polymarket_circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=60)
claude_circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=120)
