from .base_provider import BaseProvider, ProviderAuthError, ProviderQuotaError, ProviderTransientError
import os
import asyncio
from typing import Optional, List, Dict, Any, AsyncGenerator
from src.utils.logger import logger
from src.config import Config

try:
    from google import genai
    from google.genai import types, errors
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str, provider_name: str = "gemini"):
        super().__init__(api_key, provider_name)
        self.default_model = Config.load().default_model or "gemini-2.0-flash"

    def _get_client(self) -> "genai.Client":
        if not HAS_GENAI:
            raise ProviderTransientError("google-genai package is not installed.")
        return genai.Client(api_key=self.api_key)

    def _extract_text(self, payload: Dict[str, Any]) -> str:
        """Extract prompt text from common payload formats."""
        if "messages" in payload:
            return "\n".join([m.get("content", "") for m in payload["messages"] if isinstance(m, dict)])
        if "prompt" in payload:
            return payload["prompt"]
        if "input" in payload:
            return str(payload["input"])
        return ""

    async def _list_models(self, client: "genai.Client") -> List[str]:
        """Fetch available models from the API."""
        try:
            # client.models.list() is synchronous in the current SDK
            models = client.models.list()
            return [m.name for m in models if m.name]
        except Exception as e:
            logger.warning("gemini_list_models_failed", error=str(e))
            return []

    def _map_model(self, model: str, available_models: List[str]) -> str:
        """Map common model names to Gemini model names if the requested one is not found."""
        if not available_models:
            return model
        
        # Strip 'models/' prefix if present for comparison
        clean_available = [m.replace("models/", "") for m in available_models]
        clean_requested = model.replace("models/", "")

        if clean_requested in clean_available:
            return model

        # Mapping common names to Gemini equivalents
        mappings = {
            "gpt-4o": "gemini-2.0-pro-exp-02-05",
            "gpt-4o-mini": "gemini-2.0-flash",
            "claude-3-5-sonnet": "gemini-2.0-pro-exp-02-05",
            "llama-3": "gemini-2.0-flash",
        }

        mapped = mappings.get(clean_requested)
        if mapped and mapped in clean_available:
            return f"models/{mapped}" if "models/" in available_models[0] else mapped

        # Best-effort match
        for m in available_models:
            if clean_requested.lower() in m.lower():
                return m
        
        # Default fallback to a known good model if requested is totally unknown
        if "flash" in model.lower() or not clean_available:
            return "gemini-2.0-flash"
        
        return available_models[0]

    async def request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client()
        model = payload.get("model") or self.default_model
        prompt = self._extract_text(payload)

        try:
            # Using run_in_executor for sync SDK calls to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            
            try:
                response = await loop.run_in_executor(
                    None, 
                    lambda: client.models.generate_content(model=model, contents=prompt)
                )
            except errors.ClientError as e:
                # google.genai.errors.ClientError has .code
                code = getattr(e, "code", getattr(e, "status_code", 500))
                # Handle model not found (404) with fallback
                if code == 404:
                    available = await self._list_models(client)
                    new_model = self._map_model(model, available)
                    if new_model != model:
                        logger.info("gemini_model_fallback", original=model, fallback=new_model)
                        response = await loop.run_in_executor(
                            None,
                            lambda: client.models.generate_content(model=new_model, contents=prompt)
                        )
                    else:
                        raise
                else:
                    raise

            return {
                "output": response.text,
                "usage": {
                    "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                    "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                    "total_tokens": getattr(response.usage_metadata, "total_token_count", 0),
                }
            }

        except errors.ClientError as e:
            # google.genai.errors.ClientError has .code, not .status_code
            code = getattr(e, "code", getattr(e, "status_code", 500))
            if code == 401:
                raise ProviderAuthError(f"Gemini Auth Failed: {str(e)}")
            if code == 429:
                raise ProviderQuotaError(f"Gemini Quota Exceeded: {str(e)}")
            raise ProviderTransientError(f"Gemini Client Error ({code}): {str(e)}")
        except Exception as e:
            logger.exception("gemini_request_exception", error=str(e))
            raise ProviderTransientError(f"Gemini Unexpected Error: {str(e)}")

    async def stream(self, payload: Dict[str, Any]) -> AsyncGenerator[str, None]:
        client = self._get_client()
        model = payload.get("model") or self.default_model
        prompt = self._extract_text(payload)

        try:
            # The google-genai SDK's generate_content_stream is a generator
            # We wrap it to make it async-friendly
            def sync_stream():
                return client.models.generate_content_stream(model=model, contents=prompt)

            loop = asyncio.get_event_loop()
            # Since the SDK is synchronous, we run the iterator in a thread
            # and yield from it.
            
            # For simplicity in this async environment, we'll use a thread-safe queue
            # or just run it as a whole if the SDK doesn't support async generators natively yet.
            # Actually, let's use the provided synchronous generator in a thread.
            
            response_stream = await loop.run_in_executor(None, sync_stream)
            
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text

        except errors.ClientError as e:
            code = getattr(e, "code", getattr(e, "status_code", 500))
            if code == 401:
                raise ProviderAuthError(f"Gemini Auth Failed: {str(e)}")
            if code == 429:
                raise ProviderQuotaError(f"Gemini Quota Exceeded: {str(e)}")
            raise ProviderTransientError(f"Gemini Stream Error ({code}): {str(e)}")
        except Exception as e:
            logger.exception("gemini_stream_exception", error=str(e))
            raise ProviderTransientError(f"Gemini Stream Unexpected Error: {str(e)}")

    async def test_key(self) -> bool:
        """Validate the API key with a minimal call."""
        client = self._get_client()
        try:
            loop = asyncio.get_event_loop()
            # Simple list_models call to verify the key
            await loop.run_in_executor(None, client.models.list)
            return True
        except errors.ClientError as e:
            code = getattr(e, "code", getattr(e, "status_code", 500))
            if code in (401, 403):
                raise ProviderAuthError(f"Invalid Gemini API Key: {str(e)}")
            if code == 429:
                # Quota error means key is valid but exhausted
                return True 
            raise ProviderTransientError(f"Gemini test_key failed ({code}): {str(e)}")
        except Exception as e:
            logger.exception("gemini_test_key_exception", error=str(e))
            raise ProviderTransientError(f"Gemini test_key unexpected error: {str(e)}")
