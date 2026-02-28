import asyncio
import functools
import random
from typing import Type, Tuple, Callable, Any, Optional
from src.utils.logger import logger

def retry(
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: bool = True
):
    """
    Decorator for retrying async functions with exponential backoff.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(
                            "retry_limit_reached",
                            func=func.__name__,
                            attempt=attempt,
                            error=str(e)
                        )
                        raise
                    
                    # Calculate delay with jitter
                    current_delay = delay
                    if jitter:
                        current_delay *= (0.5 + random.random())
                    
                    logger.warning(
                        "retrying_func",
                        func=func.__name__,
                        attempt=attempt + 1,
                        delay=round(current_delay, 2),
                        error=str(e)
                    )
                    
                    await asyncio.sleep(current_delay)
                    delay *= backoff_factor
            
            if last_exception:
                raise last_exception
                
        return wrapper
    return decorator
