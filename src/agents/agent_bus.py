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

    async def run(self, initial_context: dict) -> dict:
        if not self.specs:
            return {}
            
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
                break
            await asyncio.gather(*(run_agent(s) for s in to_run))

        return self.results
