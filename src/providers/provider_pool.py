<<<<<<< HEAD
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
=======
"""Provider pool — singleton, multi-provider failover with correct key rotation."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Set

from src.db import key_store
from src.providers.base_provider import ProviderAuthError, ProviderQuotaError, ProviderTransientError
from src.utils.logger import logger

_VIRTUAL_KEY_USAGE: Dict[str, datetime] = {}
_MAX_TRANSIENT_PER_KEY = 3
_KEYLESS_PROVIDERS = frozenset({"ollama", "g4f"})

_pool_instance: Optional["ProviderPool"] = None

def get_pool() -> "ProviderPool":
    global _pool_instance
    if _pool_instance is None:
        _pool_instance = ProviderPool()
    return _pool_instance

class ProviderPool:
    def __init__(self) -> None:
        self._locks: Dict[tuple, asyncio.Lock] = {}

    def _get_lock(self, user_id: int, provider: str) -> asyncio.Lock:
        key = (user_id, self._normalize(provider))
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def request_with_key(self, user_id: int, provider: str, payload: dict) -> dict:
        norm = self._normalize(provider)
        if norm in _KEYLESS_PROVIDERS:
            adapter = self._make_adapter(norm, "")
            try:
                return await adapter.request(payload)
            except (ProviderAuthError, ProviderQuotaError, ProviderTransientError):
                raise
            except Exception as exc:
                raise ProviderTransientError(str(exc))

        tried: Set[str] = set()
        transient_streak = 0

        while True:
            async with self._get_lock(user_id, norm):
                k = await self._select_key(user_id, norm, exclude=tried)

            if k is None:
                raise RuntimeError(f"All {provider} keys exhausted ({len(tried)} tried).")

            api_key: str = k["raw_key"]
            adapter = self._make_adapter(norm, api_key)

            try:
                resp = await adapter.request(payload)
                await self._record_usage(k)
                # Token accounting
                usage = resp.get("usage")
                if usage and k["id"] >= 0:
                    tokens = usage.get("total_tokens") or usage.get("total_token_count", 0)
>>>>>>> 7599a86 (Upgrade: From rika-bot to rika-agent)
                    if tokens:
                        try:
                            await key_store.increment_tokens_used(k["id"], int(tokens))
                        except Exception:
                            pass
<<<<<<< HEAD
                
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
            
=======
                return resp

            except ProviderAuthError as exc:
                logger.error("key_auth_failed", key_id=k["id"], provider=norm, error=str(exc))
                if k["id"] >= 0:
                    await key_store.blacklist_key(k["id"], reason="auth_failed")
                tried.add(api_key)
                transient_streak = 0

            except ProviderQuotaError as exc:
                err_lower = str(exc).lower()
                is_rate_limit = any(x in err_lower for x in ["429","rate limit","too many","tpm","rpm"])
                if is_rate_limit:
                    tried.add(api_key)
                    transient_streak = 0
                    next_k = await self._select_key(user_id, norm, exclude=tried)
                    if next_k is None:
                        tried.discard(api_key)
                        await asyncio.sleep(5)
                else:
                    logger.warning("hard_quota_blacklisting", provider=norm, key_id=k["id"])
                    if k["id"] >= 0:
                        await key_store.blacklist_key(k["id"], reason="quota_exceeded",
                                                      quota_resets_at=self._estimate_reset(norm))
                    tried.add(api_key)
                    transient_streak = 0

            except (ProviderTransientError, Exception) as exc:
                transient_streak += 1
                logger.warning("transient_error", provider=norm, key_id=k["id"],
                               streak=transient_streak, error=str(exc))
                if transient_streak >= _MAX_TRANSIENT_PER_KEY:
                    tried.add(api_key)
                    transient_streak = 0
                else:
                    await asyncio.sleep(min(2 ** transient_streak, 30))

    async def stream_with_key(self, user_id: int, provider: str, payload: dict):
        norm = self._normalize(provider)
        if norm in _KEYLESS_PROVIDERS:
            async for chunk in self._make_adapter(norm, "").stream(payload):
                yield chunk
            return
        k = await self._select_key(user_id, norm)
        if k is None:
            raise RuntimeError(f"No key available for {provider}")
        adapter = self._make_adapter(norm, k["raw_key"])
        try:
            async for chunk in adapter.stream(payload):
                yield chunk
            await self._record_usage(k)
        except (ProviderQuotaError, ProviderAuthError) as exc:
            reason = "auth_failed" if isinstance(exc, ProviderAuthError) else "quota_exceeded"
            if k["id"] >= 0:
                await key_store.blacklist_key(k["id"], reason=reason)
            raise

    async def get_healthy_key(self, user_id: int, provider: str) -> Optional[dict]:
        norm = self._normalize(provider)
        if norm in _KEYLESS_PROVIDERS:
            adapter = self._make_adapter(norm, "")
            try:
                ok = await adapter.test_key()
                return {"id": -99, "provider": norm, "raw_key": "", "is_blacklisted": False} if ok else None
            except Exception:
                return None
        k = await self._select_key(user_id, norm)
        if k is None:
            return None
        adapter = self._make_adapter(norm, k["raw_key"])
        try:
            if await adapter.test_key():
                return k
        except (ProviderAuthError, ProviderQuotaError) as exc:
            reason = "auth_failed" if isinstance(exc, ProviderAuthError) else "quota_exceeded"
            if k["id"] >= 0:
                await key_store.blacklist_key(k["id"], reason=reason)
        except Exception:
            pass
        return None


    async def request_with_key_structured(self, user_id: int, provider: str,
                                           payload: dict, tool_schemas: list) -> "StructuredResponse":
        """Like request_with_key but returns a StructuredResponse for function calling."""
        from src.providers.base_provider import StructuredResponse
        norm = self._normalize(provider)
        if norm in _KEYLESS_PROVIDERS:
            adapter = self._make_adapter(norm, "")
            return await adapter.request_with_tools(payload, tool_schemas)
        k = await self._select_key(user_id, norm)
        if k is None:
            raise RuntimeError(f"No key for {provider}")
        adapter = self._make_adapter(norm, k["raw_key"])
        try:
            resp = await adapter.request_with_tools(payload, tool_schemas)
            await self._record_usage(k)
            return resp
        except Exception:
            raise

    async def _select_key(self, user_id: int, provider: str, exclude: Optional[Set[str]] = None) -> Optional[dict]:
        exclude = exclude or set()
        db_keys = await key_store.list_api_keys(user_id)
        norm_p = self._normalize(provider)
        provider_keys = [k for k in db_keys if self._normalize(k.get("provider", "")) == norm_p]
        env_str = os.environ.get(f"{provider.upper()}_API_KEY", "")
        for i, raw in enumerate([r.strip() for r in env_str.replace(",", " ").split() if r.strip()]):
            usage_key = f"{provider}:{raw[:12]}"
            provider_keys.append({"id": -(i+1), "provider": provider, "raw_key": raw,
                                  "is_blacklisted": False,
                                  "last_used_at": _VIRTUAL_KEY_USAGE.get(usage_key, datetime.min).isoformat(),
                                  "quota_resets_at": None, "usage_key": usage_key})
        if not provider_keys:
            return None

        def _lru(k):
            try:
                return datetime.fromisoformat(k.get("last_used_at") or "1970-01-01T00:00:00")
            except ValueError:
                return datetime.min

        for k in sorted(provider_keys, key=_lru):
            if k.get("is_blacklisted"):
                reset = k.get("quota_resets_at")
                if reset:
                    try:
                        if datetime.fromisoformat(reset) <= datetime.utcnow():
                            if k["id"] >= 0:
                                await key_store.unblacklist_key(k["id"])
                            k["is_blacklisted"] = False
                        else:
                            continue
                    except ValueError:
                        continue
                else:
                    continue
            if k["id"] >= 0 and "raw_key" not in k:
                try:
                    k["raw_key"] = (await key_store.get_api_key_raw(k["id"])).decode("utf-8")
                except Exception:
                    if k["id"] >= 0:
                        await key_store.blacklist_key(k["id"], reason="decryption_failed")
                    continue
            if k.get("raw_key", "") in exclude:
                continue
            return k
        return None

    async def _record_usage(self, k: dict) -> None:
        if k["id"] >= 0:
>>>>>>> 7599a86 (Upgrade: From rika-bot to rika-agent)
            try:
                await key_store.update_key_last_used(k["id"])
            except Exception:
                pass
<<<<<<< HEAD
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
            
=======
        elif k.get("usage_key"):
            _VIRTUAL_KEY_USAGE[k["usage_key"]] = datetime.utcnow()

    def _normalize(self, name: str) -> str:
        n = (name or "").lower().strip()
        return "gemini" if n in ("google", "gemini") else n

    def _make_adapter(self, provider: str, api_key: str):
        norm = self._normalize(provider)
        if norm == "gemini":
            from src.providers.gemini_provider import GeminiProvider
            return GeminiProvider(api_key)
        if norm == "openrouter":
            from src.providers.openrouter_provider import OpenRouterProvider
            return OpenRouterProvider(api_key)
        if norm == "groq":
            from src.providers.groq_provider import GroqProvider
            return GroqProvider(api_key)
        if norm == "ollama":
            from src.providers.ollama_provider import OllamaProvider
            return OllamaProvider()
        if norm == "g4f":
            from src.providers.g4f_provider import G4FProvider
            return G4FProvider()
        from src.providers.openrouter_provider import OpenRouterProvider
        return OpenRouterProvider(api_key)

    def _estimate_reset(self, provider: str) -> Optional[str]:
        try:
            from src.config import Config
            cfg = Config.get()
            field = f"{provider}_quota_reset_utc_hour"
            if hasattr(cfg, field):
                hour = int(getattr(cfg, field))
                now = datetime.utcnow()
                candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                if candidate <= now:
                    candidate += timedelta(days=1)
                return candidate.isoformat()
        except Exception:
            pass
>>>>>>> 7599a86 (Upgrade: From rika-bot to rika-agent)
        return None
