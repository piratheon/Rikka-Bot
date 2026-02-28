from __future__ import annotations
import asyncio
from typing import Dict, Any
from src.tools.registry import build_registry
from src.config import Config
from src.providers.provider_pool import ProviderPool
from src.utils.logger import logger


class Agent:
    """Lightweight agent runner that can call registered tools and/or providers.

    This is intentionally minimal: it supports two modes:
    - If the prompt starts with `tool:` the agent will parse `tool:name arg` and
      call the corresponding tool from the registry.
    - Otherwise it forwards the prompt to the provider pool using the configured
      provider priority (first available key).
    """

    def __init__(self, config: Config | None = None):
        self.config = config or Config.load()
        self.registry = build_registry(self.config)
        self.pool = ProviderPool()

    async def run(self, user_id: int, prompt: str) -> Dict[str, Any]:
        # Simple tool invocation syntax: "tool:web_fetch https://example.com"
        try:
            if prompt.startswith("tool:"):
                parts = prompt.split(None, 1)
                if len(parts) == 1:
                    return {"error": "No tool specified"}
                tool_decl = parts[0][len("tool:"):]
                arg = parts[1] if len(parts) > 1 else ""
                tool = self.registry.get(tool_decl)
                if not tool:
                    return {"error": f"tool {tool_decl} not found"}
                # allow both sync and async tools
                if asyncio.iscoroutinefunction(tool):
                    res = await tool(arg)
                else:
                    res = tool(arg)
                return {"tool": tool_decl, "result": res}

            # Otherwise forward to providers using priority
            priorities = self.config.default_provider_priority or ["groq", "openrouter", "gemini"]
            model = getattr(self.config, "default_model", "gemini-2.5-flash")
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": self.config.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 512,
            }
            for provider in priorities:
                try:
                    k = await self.pool.get_cached_key(user_id, provider)
                except Exception:
                    k = None
                if not k:
                    continue
                try:
                    resp = await self.pool.request_with_key(user_id, provider, payload)
                    return {"provider": provider, "response": resp}
                except Exception as e:
                    logger.warning("agent_provider_failed", provider=provider, error=str(e))
                    continue
            return {"error": "no providers available"}
        except Exception as e:
            logger.exception("agent_run_failed", error=str(e))
            return {"error": str(e)}
