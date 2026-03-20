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
                    if tokens:
                        try:
                            await key_store.increment_tokens_used(k["id"], int(tokens))
                        except Exception:
                            pass
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
            try:
                await key_store.update_key_last_used(k["id"])
            except Exception:
                pass
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
        return None
