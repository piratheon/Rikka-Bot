<<<<<<< HEAD
import asyncio
from typing import List
from .agent_models import AgentSpec
from .agent_factory import AgentFactory


class AgentBus:
    """Simple orchestration: run agents with no dependencies in parallel,
    and run dependent agents after their inputs are ready.
    This is a minimal initial implementation to be expanded.
    """

    def __init__(self, specs: List[AgentSpec], bubble=None):
        self.specs = {s.id: s for s in specs}
        self.bubble = bubble
        self.results = {}
=======
"""AgentBus — parallel + dependency-ordered runner with locked results dict."""
from __future__ import annotations
import asyncio
from typing import List
from src.agents.agent_models import AgentSpec
from src.agents.agent_factory import AgentFactory
from src.utils.logger import logger

class AgentBus:
    def __init__(self, specs: List[AgentSpec], bubble=None, depth: int = 0) -> None:
        self.specs = {s.id: s for s in specs}
        self.bubble = bubble
        self.depth = depth
        self.results: dict = {}
        self._lock = asyncio.Lock()
>>>>>>> 7599a86 (Upgrade: From rika-bot to rika-agent)

    async def run(self, initial_context: dict) -> dict:
        if not self.specs:
            return {}
<<<<<<< HEAD
            
        # find agents with no depends_on
        ready = [s for s in self.specs.values() if not s.depends_on]
        pending = {s.id: s for s in self.specs.values() if s.depends_on}

        async def run_agent(spec):
            agent = AgentFactory.create(spec, bubble=self.bubble)
            if self.bubble:
                self.bubble.update(spec.id, "running...")
            try:
                # Add current results to the context for this agent
                run_context = initial_context.copy()
                run_context["results"] = self.results
                out = await agent.run(run_context)
                self.results[spec.id] = out
                if self.bubble:
                    self.bubble.update(spec.id, "done")
            except Exception as e:
                self.results[spec.id] = {"error": str(e)}
                if self.bubble:
                    self.bubble.update(spec.id, f"error: {e}")

        # run initial agents
        await asyncio.gather(*(run_agent(s) for s in ready))

        # run dependent agents sequentially as their dependencies become available
        # naive approach: loop until no pending
        while pending:
            to_run = []
            for pid, spec in list(pending.items()):
                if all(d in self.results for d in spec.depends_on):
                    to_run.append(spec)
                    del pending[pid]
            if not to_run:
=======
        ready = [s for s in self.specs.values() if not s.depends_on]
        pending = {s.id: s for s in self.specs.values() if s.depends_on}

        async def run_agent(spec: AgentSpec) -> None:
            agent = AgentFactory.create(spec, bubble=self.bubble, depth=self.depth)
            if self.bubble: self.bubble.update(spec.id, "running...")
            try:
                ctx = {**initial_context, "results": dict(self.results)}
                out = await agent.run(ctx)
                async with self._lock:
                    self.results[spec.id] = out
                if self.bubble: self.bubble.update(spec.id, "done")
            except Exception as exc:
                logger.error("agent_bus_run_failed", agent_id=spec.id, error=str(exc))
                async with self._lock:
                    self.results[spec.id] = {"id": spec.id, "output": f"Error: {exc}"}
                if self.bubble: self.bubble.update(spec.id, f"error: {exc}")

        if ready:
            await asyncio.gather(*(run_agent(s) for s in ready))

        max_waves = len(pending) + 1
        for wave in range(max_waves):
            if not pending:
                break
            to_run = []
            async with self._lock:
                current = set(self.results.keys())
            for pid, spec in list(pending.items()):
                if all(d in current for d in spec.depends_on):
                    to_run.append(spec)
                    del pending[pid]
            if not to_run:
                logger.error("agent_bus_deadlock", stuck=list(pending.keys()))
>>>>>>> 7599a86 (Upgrade: From rika-bot to rika-agent)
                break
            await asyncio.gather(*(run_agent(s) for s in to_run))

        return self.results
