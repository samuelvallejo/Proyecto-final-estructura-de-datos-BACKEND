"""Decorator pattern for endpoint timing.

``measured`` wraps a function that returns a dict and adds how long it took,
so every endpoint reports its server time the same way without repeating the
perf_counter code. ``functools.wraps`` keeps the original signature, which
FastAPI reads to build query parameters and dependencies.
"""
import time
from functools import wraps


def measured(field: str = 'tookMs'):
    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            result = function(*args, **kwargs)
            if isinstance(result, dict):
                result[field] = round((time.perf_counter() - started) * 1000, 2)
            return result
        return wrapper
    return decorate
