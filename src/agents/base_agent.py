import asyncio
from typing import Any


class BaseAgent:
    def __init__(self, spec: Any, bubble=None):
        self.spec = spec
        self.bubble = bubble
        self.status = "pending"

    async def run(self, context: dict) -> dict:
        """Run the agent. Should be overridden by subclasses.

        Returns a dict matching the agent's `output_schema`.
        """
        # Default behaviour: echo the prompt back
        await asyncio.sleep(0)
        return {"result": f"Agent {self.spec.name} ran with context."}
