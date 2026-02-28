from __future__ import annotations
import abc
from typing import Any, AsyncIterator


class ProviderError(Exception):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderQuotaError(ProviderError):
    pass


class ProviderTransientError(ProviderError):
    pass


class BaseProvider(abc.ABC):
    """Abstract provider adapter.

    Concrete providers should implement `async def request(...)` and
    `async def test_key()` for validation.
    """

    def __init__(self, api_key: str, provider_name: str):
        self.api_key = api_key
        self.provider_name = provider_name

    @abc.abstractmethod
    async def request(self, payload: dict) -> dict:
        """Send a completion request and return a parsed response dict."""

    @abc.abstractmethod
    async def stream(self, payload: dict) -> AsyncIterator[str]:
        """Optional streaming generator yielding chunks of text."""

    @abc.abstractmethod
    async def test_key(self) -> bool:
        """Run a minimal call to validate `self.api_key`. Return True if valid."""
