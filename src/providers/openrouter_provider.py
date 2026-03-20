<<<<<<< HEAD
from .base_provider import BaseProvider
import os
import httpx
from src.utils.logger import logger


class OpenRouterProvider(BaseProvider):
    def __init__(self, api_key: str, provider_name: str = "openrouter"):
        super().__init__(api_key, provider_name)
        self.base_url = os.environ.get("OPENROUTER_BASE_URL", "https://api.openrouter.ai")

    async def request(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.base_url}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            r = await client.post(url, json=payload, headers=headers)
            logger.info("openrouter_request", url=url, status=r.status_code)
            if r.status_code == 401:
                from .base_provider import ProviderAuthError
                raise ProviderAuthError("Unauthorized")
            if r.status_code == 429:
                from .base_provider import ProviderQuotaError
                raise ProviderQuotaError("Quota exceeded")
            r.raise_for_status()
            
            data = r.json()
            output = ""
            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                if "message" in choice:
                    output = choice["message"].get("content", "")
                else:
                    output = choice.get("text", "")
            
            return {
                "output": output,
                "usage": data.get("usage", {}),
                "raw_response": data
            }

    async def stream(self, payload: dict):
        async with httpx.AsyncClient(timeout=None) as client:
            url = f"{self.base_url}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                logger.info("openrouter_stream_start", url=url, status=resp.status_code)
                if resp.status_code == 401:
                    from .base_provider import ProviderAuthError

                    raise ProviderAuthError("Unauthorized")
                if resp.status_code == 429:
                    from .base_provider import ProviderQuotaError

                    raise ProviderQuotaError("Quota exceeded")
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    s = chunk.decode(errors="ignore")
                    yield s

    async def test_key(self) -> bool:
        # Minimal validation: GET /v1/models or a heartbeat endpoint
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{self.base_url}/v1/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            try:
                r = await client.get(url, headers=headers)
                logger.info("openrouter_test", url=url, status=r.status_code)
                if r.status_code == 200:
                    return True
                if r.status_code == 401:
                    from .base_provider import ProviderAuthError

                    raise ProviderAuthError("Unauthorized")
                if r.status_code == 429:
                    from .base_provider import ProviderQuotaError

                    raise ProviderQuotaError("Quota exceeded")
                return False
            except httpx.HTTPStatusError:
                from .base_provider import ProviderTransientError

                raise ProviderTransientError("HTTP error")
            except Exception:
                from .base_provider import ProviderTransientError

                raise ProviderTransientError("Network error")
=======
"""OpenRouter provider — OpenAI-compatible with function calling."""
from __future__ import annotations
import json, os
import httpx
from typing import Any, AsyncGenerator, Dict, List
from src.providers.base_provider import (BaseProvider, ProviderAuthError, ProviderQuotaError,
                                          ProviderTransientError, StructuredResponse)
from src.utils.logger import logger

class OpenRouterProvider(BaseProvider):
    SUPPORTS_FUNCTION_CALLING = True

    def __init__(self, api_key: str, provider_name: str = "openrouter"):
        super().__init__(api_key, provider_name)
        self.base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/piratheon/rk-agent",
            "X-Title": "rk-agent",
        }

    def _raise(self, r: httpx.Response) -> None:
        if r.status_code == 401: raise ProviderAuthError(f"OpenRouter auth: {r.text[:200]}")
        if r.status_code == 429: raise ProviderQuotaError(f"OpenRouter quota: {r.text[:200]}")
        if r.status_code >= 400: raise ProviderTransientError(f"OpenRouter {r.status_code}: {r.text[:200]}")

    async def request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{self.base_url}/api/v1/chat/completions",
                                  json=payload, headers=self._headers())
            self._raise(r)
            data = r.json()
            content = self._extract_openai_content(data.get("choices", []))
            return {"output": content or "", "usage": data.get("usage", {})}

    async def request_with_tools(self, payload: Dict[str, Any], tool_schemas: List[Any]) -> StructuredResponse:
        payload = dict(payload)
        if tool_schemas:
            payload["tools"] = [s.to_openai() for s in tool_schemas]
            payload["tool_choice"] = "auto"
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{self.base_url}/api/v1/chat/completions",
                                  json=payload, headers=self._headers())
            self._raise(r)
            data = r.json()
            choices = data.get("choices", [])
            tool_calls = self._parse_openai_tool_calls(choices) if tool_schemas else []
            content = self._extract_openai_content(choices) or ""
            return StructuredResponse(content=content, tool_calls=tool_calls,
                                      usage=data.get("usage", {}), model=data.get("model", ""))

    async def stream(self, payload: Dict[str, Any]) -> AsyncGenerator[str, None]:
        payload = dict(payload)
        payload["stream"] = True
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self.base_url}/api/v1/chat/completions",
                                     json=payload, headers=self._headers()) as resp:
                self._raise(resp)
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "): continue
                    raw = line[6:]
                    if raw == "[DONE]": break
                    try:
                        delta = json.loads(raw)["choices"][0].get("delta", {})
                        if c := delta.get("content"): yield c
                    except Exception: continue

    async def test_key(self) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{self.base_url}/api/v1/models", headers=self._headers())
            if r.status_code == 200: return True
            if r.status_code == 401: raise ProviderAuthError("OpenRouter auth failed")
            raise ProviderTransientError(f"OpenRouter test: {r.status_code}")
>>>>>>> 7599a86 (Upgrade: From rika-bot to rika-agent)
