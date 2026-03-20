"""Gemini provider — Google genai SDK with native function calling and vision."""
from __future__ import annotations
import asyncio, json
from typing import Any, AsyncGenerator, Dict, List, Optional
from src.providers.base_provider import (BaseProvider, ProviderAuthError, ProviderQuotaError,
                                          ProviderTransientError, StructuredResponse, ToolCall)
from src.utils.logger import logger
from src.config import Config

try:
    from google import genai
    from google.genai import types, errors
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

_DEFAULT = "gemini-2.0-flash"

class GeminiProvider(BaseProvider):
    SUPPORTS_FUNCTION_CALLING = True

    def __init__(self, api_key: str, provider_name: str = "gemini"):
        super().__init__(api_key, provider_name)
        self.default_model = Config.get().default_model or _DEFAULT

    def _client(self):
        if not HAS_GENAI: raise ProviderTransientError("google-genai not installed")
        return genai.Client(api_key=self.api_key)

    def _loop(self):
        return asyncio.get_running_loop()

    def _extract_messages(self, payload: Dict[str, Any]):
        """Build Gemini contents + system_instruction from OpenAI-format messages."""
        messages = payload.get("messages", [])
        system = ""
        contents = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system = content
                continue
            # Handle multimodal content (list of parts)
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append(part["text"])
                    elif part.get("type") == "image_url":
                        # base64 image from Telegram photo handler
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            media_type, b64 = url.split(";base64,")
                            media_type = media_type.replace("data:", "")
                            parts.append(types.Part.from_bytes(
                                data=__import__("base64").b64decode(b64),
                                mime_type=media_type,
                            ))
                content_str = "\n".join(p if isinstance(p, str) else "" for p in parts)
                gemini_role = "user" if role == "user" else "model"
                contents.append(types.Content(
                    role=gemini_role,
                    parts=[p if not isinstance(p, str) else types.Part.from_text(p) for p in parts]
                ))
            else:
                gemini_role = "user" if role == "user" else "model"
                contents.append(types.Content(role=gemini_role,
                                              parts=[types.Part.from_text(str(content))]))
        return contents, system

    def _resolve_model(self, payload: Dict[str, Any]) -> str:
        model = payload.get("model") or self.default_model
        if "gemini" not in model.lower():
            return self.default_model
        return model

    async def request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        client = self._client()
        model = self._resolve_model(payload)
        contents, system = self._extract_messages(payload)
        config = types.GenerateContentConfig(system_instruction=system) if system else None
        try:
            resp = await self._loop().run_in_executor(
                None, lambda: client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            )
            return {
                "output": resp.text or "",
                "usage": {
                    "prompt_tokens": getattr(resp.usage_metadata, "prompt_token_count", 0),
                    "completion_tokens": getattr(resp.usage_metadata, "candidates_token_count", 0),
                    "total_tokens": getattr(resp.usage_metadata, "total_token_count", 0),
                }
            }
        except errors.ClientError as e:
            code = getattr(e, "code", 500)
            if code == 401: raise ProviderAuthError(str(e))
            if code == 429: raise ProviderQuotaError(str(e))
            raise ProviderTransientError(str(e))
        except Exception as e:
            raise ProviderTransientError(str(e))

    async def request_with_tools(self, payload: Dict[str, Any], tool_schemas: List[Any]) -> StructuredResponse:
        client = self._client()
        model = self._resolve_model(payload)
        contents, system = self._extract_messages(payload)
        config_kwargs: Dict[str, Any] = {}
        if system:
            config_kwargs["system_instruction"] = system
        if tool_schemas:
            try:
                declarations = [s.to_gemini() for s in tool_schemas]
                config_kwargs["tools"] = [types.Tool(function_declarations=declarations)]
            except Exception as e:
                logger.warning("gemini_tool_schema_build_failed", error=str(e))
        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
        try:
            resp = await self._loop().run_in_executor(
                None, lambda: client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            )
            tool_calls: List[ToolCall] = []
            content_text = ""
            for part in (resp.candidates[0].content.parts if resp.candidates else []):
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    args = dict(fc.args) if fc.args else {}
                    tool_calls.append(ToolCall(name=fc.name, arguments=args))
                elif hasattr(part, "text") and part.text:
                    content_text += part.text
            usage = {
                "prompt_tokens": getattr(resp.usage_metadata, "prompt_token_count", 0),
                "completion_tokens": getattr(resp.usage_metadata, "candidates_token_count", 0),
                "total_tokens": getattr(resp.usage_metadata, "total_token_count", 0),
            }
            return StructuredResponse(content=content_text, tool_calls=tool_calls,
                                      usage=usage, model=model)
        except errors.ClientError as e:
            code = getattr(e, "code", 500)
            if code == 401: raise ProviderAuthError(str(e))
            if code == 429: raise ProviderQuotaError(str(e))
            raise ProviderTransientError(str(e))
        except Exception as e:
            raise ProviderTransientError(str(e))

    async def stream(self, payload: Dict[str, Any]) -> AsyncGenerator[str, None]:
        client = self._client()
        model = self._resolve_model(payload)
        contents, system = self._extract_messages(payload)
        config = types.GenerateContentConfig(system_instruction=system) if system else None
        try:
            stream_gen = await self._loop().run_in_executor(
                None, lambda: client.models.generate_content_stream(
                    model=model, contents=contents, config=config
                )
            )
            for chunk in stream_gen:
                if chunk.text: yield chunk.text
        except errors.ClientError as e:
            code = getattr(e, "code", 500)
            if code == 401: raise ProviderAuthError(str(e))
            if code == 429: raise ProviderQuotaError(str(e))
            raise ProviderTransientError(str(e))

    async def test_key(self) -> bool:
        client = self._client()
        try:
            await self._loop().run_in_executor(None, client.models.list)
            return True
        except errors.ClientError as e:
            code = getattr(e, "code", 500)
            if code in (401, 403): raise ProviderAuthError(str(e))
            if code == 429: return True
            raise ProviderTransientError(str(e))
