from __future__ import annotations
import asyncio
from typing import Optional
from ..db import key_store
from src.utils.logger import logger
from .openrouter_provider import OpenRouterProvider
from .groq_provider import GroqProvider
from .gemini_provider import GeminiProvider
from datetime import datetime, timedelta
from src.config import Config
from src.utils.retry import retry
from .base_provider import ProviderTransientError, ProviderQuotaError, ProviderAuthError


class ProviderPool:
    """Simple LRU-style provider pool per user and provider.
    Handles key selection, decryption, validation, and blacklisting.
    """

    def __init__(self):
        self._locks: dict[tuple[int, str], asyncio.Lock] = {}

    def _normalize_provider(self, name: str) -> str:
        """Normalize provider name aliases to canonical provider keys."""
        if not name:
            return ""
        n = name.lower()
        if n in ("google", "gemini"):
            return "gemini"
        return n

    @retry(exceptions=(ProviderTransientError,), max_retries=2)
    async def request_with_key(self, user_id: int, provider: str, payload: dict) -> dict:
        """Obtain a healthy key, call provider.request, handle errors, and account tokens.
        Automatically switches to the next available key on quota or auth errors.
        """
        # We try to get a key, if it fails after request, we blacklist and try AGAIN (recursively or loop)
        # To avoid infinite loops, we can limit attempts to the number of available keys
        max_attempts = 5 # arbitrary limit
        
        for attempt in range(max_attempts):
            k = await self.get_cached_key(user_id, provider)
            if not k:
                logger.warning("no_healthy_key", user_id=user_id, provider=provider)
                raise RuntimeError(f"No healthy key available for {provider}")

            api_key = k.get("raw_key")
            adapter = self._make_adapter(provider, api_key)
            
            try:
                resp = await adapter.request(payload)
                
                # Account tokens if present in standardized format
                usage = resp.get("usage")
                if usage:
                    # Handle different usage metadata shapes
                    tokens = usage.get("total_tokens") or usage.get("total_token_count")
                    if tokens:
                        try:
                            await key_store.increment_tokens_used(k["id"], int(tokens))
                        except Exception:
                            pass
                
                # Update last used timestamp
                try:
                    await key_store.update_key_last_used(k["id"])
                except Exception:
                    pass
                    
                return resp
                
            except (ProviderQuotaError, ProviderAuthError, ProviderTransientError) as e:
                # Blacklist logic only for fatal errors
                if isinstance(e, (ProviderQuotaError, ProviderAuthError)):
                    reason = "quota_exceeded" if isinstance(e, ProviderQuotaError) else "auth_failed"
                    quota_resets_at = None
                    
                    if isinstance(e, ProviderQuotaError):
                        cfg = Config.load()
                        # Determine reset time
                        reset_field = f"{self._normalize_provider(provider)}_quota_reset_utc_hour"
                        if hasattr(cfg, reset_field):
                            hour = getattr(cfg, reset_field)
                            now = datetime.utcnow()
                            candidate = now.replace(hour=int(hour), minute=0, second=0, microsecond=0)
                            if candidate <= now:
                                candidate = candidate + timedelta(days=1)
                            quota_resets_at = candidate.isoformat()

                    logger.warning("blacklisting_key_and_retrying", key_id=k["id"], reason=reason, provider=provider, attempt=attempt+1)
                    await key_store.blacklist_key(k["id"], reason=reason, quota_resets_at=quota_resets_at)
                else:
                    logger.warning("transient_error_retrying_next_key", key_id=k["id"], provider=provider, attempt=attempt+1, error=str(e))
                
                # Continue loop to try next key
                continue
            except Exception:
                # Re-raised for retry decorator or final failure
                raise
        
        raise RuntimeError(f"Failed to get response from {provider} after {max_attempts} key attempts.")

    async def stream_with_key(self, user_id: int, provider: str, payload: dict):
        """Similar to request_with_key but for streaming."""
        k = await self.get_cached_key(user_id, provider)
        if not k:
            raise RuntimeError(f"No healthy key available for {provider}")

        api_key = k.get("raw_key")
        adapter = self._make_adapter(provider, api_key)
        
        try:
            async for chunk in adapter.stream(payload):
                yield chunk
            
            try:
                await key_store.update_key_last_used(k["id"])
            except Exception:
                pass
        except (ProviderQuotaError, ProviderAuthError) as e:
            # Blacklist on fatal errors during stream
            reason = "quota_exceeded" if isinstance(e, ProviderQuotaError) else "auth_failed"
            await key_store.blacklist_key(k["id"], reason=reason)
            raise

    def _make_adapter(self, provider: str, api_key: str):
        p = self._normalize_provider(provider)
        if p == "gemini":
            return GeminiProvider(api_key)
        if p == "openrouter":
            return OpenRouterProvider(api_key)
        if p == "groq":
            return GroqProvider(api_key)
        return OpenRouterProvider(api_key)

    async def get_cached_key(self, user_id: int, provider: str) -> Optional[dict]:
        """LRU selection of a non-blacklisted key. Decrypts on the fly."""
        keys = await key_store.list_api_keys(user_id)
        
        # Filter and sort by last_used_at (None first)
        provider_keys = [k for k in keys if self._normalize_provider(k.get("provider")) == self._normalize_provider(provider)]
        if not provider_keys:
            return None
            
        def _last_used_sort(k):
            v = k.get("last_used_at")
            return v or "1970-01-01T00:00:00"

        sorted_keys = sorted(provider_keys, key=_last_used_sort)
        
        # Phase 1: Try non-blacklisted (or recently reset) keys
        for k in sorted_keys:
            if k["is_blacklisted"]:
                # If it has a reset time, check if it's passed
                reset_at = k.get("quota_resets_at")
                if reset_at:
                    if datetime.fromisoformat(reset_at) <= datetime.utcnow():
                        await key_store.unblacklist_key(k["id"])
                        k["is_blacklisted"] = False
                    else:
                        continue
                else:
                    # Blacklisted without reset time — skip in first pass
                    continue

            # Decrypt
            try:
                raw = await key_store.get_api_key_raw(k["id"])
                k["raw_key"] = raw.decode("utf-8")
                return k
            except Exception:
                logger.exception("decryption_failed", key_id=k["id"])
                await key_store.blacklist_key(k["id"], reason="decryption_failed")
                continue
        
        # Phase 2: Last resort — try blacklisted keys with NO reset time (e.g. auth_failed or transient)
        # This allows lazy re-validation if the user fixed the key or it was a false positive.
        for k in sorted_keys:
            if k["is_blacklisted"] and not k.get("quota_resets_at"):
                try:
                    raw = await key_store.get_api_key_raw(k["id"])
                    k["raw_key"] = raw.decode("utf-8")
                    logger.info("trying_blacklisted_key_as_last_resort", key_id=k["id"], provider=provider)
                    return k
                except Exception:
                    continue
                
        return None

    async def get_healthy_key(self, user_id: int, provider: str) -> Optional[dict]:
        """Selects a key and performs a test_key() call."""
        k = await self.get_cached_key(user_id, provider)
        if not k:
            return None
            
        adapter = self._make_adapter(provider, k["raw_key"])
        try:
            if await adapter.test_key():
                return k
        except (ProviderAuthError, ProviderQuotaError) as e:
            reason = "auth_failed" if isinstance(e, ProviderAuthError) else "quota_exceeded"
            await key_store.blacklist_key(k["id"], reason=reason)
        except Exception:
            pass
            
        return None
