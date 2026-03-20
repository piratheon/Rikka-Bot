"""Core orchestration logic.

The Orchestrator is used for the main thought loop in run_orchestration_background.
DefaultAgent has been removed — it was a stub that returned fake output.
"""
from __future__ import annotations

from src.config import Config
from src.providers.provider_pool import get_pool
from src.utils.logger import logger


class Orchestrator:
    """Drives the next step in the ReAct thought loop."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.get()
        self.pool = get_pool()

    async def generate_step(self, user_id: int, message_history: list) -> str:
        has_system = any(m.get("role") == "system" for m in message_history)
        if not has_system:
            message_history.insert(
                0,
                {
                    "role": "system",
                    "content": self.config.system_prompt
                    + "\n\nACT AS THE CENTRAL ORCHESTRATION MIND.",
                },
            )

        payload = {
            "model": self.config.default_model,
            "messages": message_history,
        }

        priorities = self.config.default_provider_priority or ["gemini", "groq", "openrouter"]
        for provider in priorities:
            try:
                resp = await self.pool.request_with_key(user_id, provider, payload)
                return resp.get("output", "")
            except Exception as exc:
                logger.warning("orchestrator_step_failed", provider=provider, error=str(exc))

        return "Error: all providers failed for this thought step."
