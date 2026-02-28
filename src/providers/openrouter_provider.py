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
