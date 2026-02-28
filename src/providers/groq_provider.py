from .base_provider import BaseProvider, ProviderAuthError, ProviderQuotaError, ProviderTransientError
import os
import httpx
from src.utils.logger import logger


class GroqProvider(BaseProvider):
    def __init__(self, api_key: str, provider_name: str = "groq"):
        super().__init__(api_key, provider_name)
        # Groq OpenAI-compatible base URL
        self.base_url = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai")

    async def request(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.base_url}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            # Use Groq-specific model if the requested one is not likely to work
            model = payload.get("model")
            if not model or "gemini" in model.lower() or "gpt" in model.lower():
                payload = payload.copy()
                payload["model"] = "llama-3.3-70b-versatile"
                
            try:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code == 401:
                    raise ProviderAuthError(f"Groq Auth Failed: {r.text}")
                if r.status_code == 429:
                    raise ProviderQuotaError(f"Groq Quota Exceeded: {r.text}")
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
            except httpx.HTTPStatusError as e:
                logger.error("groq_request_http_error", status=e.response.status_code, text=e.response.text)
                raise ProviderTransientError(f"Groq HTTP Error: {e}")
            except Exception as e:
                logger.exception("groq_request_exception", error=str(e))
                raise ProviderTransientError(f"Groq Unexpected Error: {e}")

    async def stream(self, payload: dict):
        async with httpx.AsyncClient(timeout=None) as client:
            url = f"{self.base_url}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            # Use Groq-specific model
            model = payload.get("model")
            if not model or "gemini" in model.lower() or "gpt" in model.lower():
                payload = payload.copy()
                payload["model"] = "llama-3.3-70b-versatile"
                
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code == 401:
                    raise ProviderAuthError("Groq Auth Failed")
                if resp.status_code == 429:
                    raise ProviderQuotaError("Groq Quota Exceeded")
                resp.raise_for_status()
                async for chunk in resp.aiter_lines():
                    if chunk.startswith("data: "):
                        data = chunk[6:]
                        if data == "[DONE]":
                            break
                        import json
                        try:
                            parsed = json.loads(data)
                            delta = parsed["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except Exception:
                            continue

    async def test_key(self) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Use lightweight chat completion for testing
            url = f"{self.base_url}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5
            }
            try:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code == 200:
                    return True
                if r.status_code == 401:
                    raise ProviderAuthError("Groq Auth Failed")
                if r.status_code == 429:
                    raise ProviderQuotaError("Groq Quota Exceeded")
                raise ProviderTransientError(f"Groq Unexpected Status: {r.status_code}")
            except Exception as e:
                if isinstance(e, (ProviderAuthError, ProviderQuotaError)):
                    raise
                logger.warning("groq_test_failed", error=str(e))
                raise ProviderTransientError(f"Groq Test Failed: {e}")
