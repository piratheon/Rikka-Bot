import json
from .base_agent import BaseAgent
from .agent_models import TaskPlan, AgentSpec
from src.providers.provider_pool import ProviderPool
from src.config import Config
from src.utils.logger import logger

ORCHESTRATOR_SYSTEM_PROMPT = """
You are Rikka's Orchestration Core. Your goal is to break down user requests into a series of specialized agent tasks ONLY if necessary.

Efficiency is key:
1. If the task is straightforward, use 0 or 1 specialized agents.
2. Only spawn multiple agents if there are parallelizable sub-tasks or complex research requirements.
3. If no research is needed, set "agents": [] and provide a "final_synthesis_prompt" that Rikka can use to reply directly.

You must output ONLY a valid JSON object matching the TaskPlan schema:
{
  "reasoning": "Brief explanation of why this plan was chosen",
  "agents": [
    {
      "id": "agent_id_unique",
      "name": "Short name",
      "role": "Specific role",
      "system_prompt": "Detailed persona and task for this agent",
      "tools": ["curl", "wikipedia_search", "save_memory", "get_memories", "save_skill"],
      "depends_on": ["other_agent_id"],
      "model_preference": "smart"
    }
  ],
  "final_synthesis_prompt": "Prompt for Rikka to synthesize all agent outputs (or directly answer) for Oni-San"
}

Available tools: 
- curl: Powerful web fetcher. Use this to get content from ANY website URL. If you get SSL errors, you can use "URL --insecure" to skip verification.
- wikipedia_search: Use for general facts and history from Wikipedia.
- save_memory: Save important information about Oni-San or facts. Format: "key | value"
- get_memories: Retrieve all your persistent memories and skills.
- save_skill: Save a useful snippet, prompt, or knowledge for future use. Format: "name | description"

Remember: Rikka is confident and efficient. Don't waste resources!
"""

class Orchestrator:
    """The core logic that generates a TaskPlan from a user message."""
    
    def __init__(self, config: Config | None = None):
        self.config = config or Config.load()
        self.pool = ProviderPool()

    async def generate_plan(self, user_id: int, message: str) -> TaskPlan:
        """Calls an LLM to generate a structured TaskPlan for the given message."""
        
        priorities = self.config.default_provider_priority or ["gemini", "groq", "openrouter"]
        
        payload = {
            "model": self.config.default_model,
            "messages": [
                {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
                {"role": "user", "content": f"Task: {message}"}
            ],
            "response_format": {"type": "json_object"}
        }

        for provider in priorities:
            try:
                resp = await self.pool.request_with_key(user_id, provider, payload)
                output = resp.get("output", "")
                
                # Try to find JSON in the output if not strictly JSON
                if "{" in output:
                    start = output.find("{")
                    end = output.rfind("}") + 1
                    output = output[start:end]
                
                plan_dict = json.loads(output)
                return TaskPlan.model_validate(plan_dict)
            except Exception as e:
                logger.warning("orchestrator_provider_failed", provider=provider, error=str(e))
                continue
        
        # Fallback minimal plan if all else fails
        return TaskPlan(
            reasoning="All advanced planning failed. Falling back to direct reply.",
            agents=[
                AgentSpec(
                    id="fallback_agent",
                    name="Rikka",
                    role="Assistant",
                    system_prompt=self.config.system_prompt,
                    tools=["wikipedia_search", "curl", "get_memories"]
                )
            ],
            final_synthesis_prompt="Synthesize the findings for Oni-San."
        )

class RikkaAgent(BaseAgent):
    """The default agent used when no specialized agents are needed or as a fallback."""
    async def run(self, context: dict) -> dict:
        message = context.get("message") or ""
        # In a real run, this would be the synthesis step
        return {"reply": f"Rikka processed your request: {message}"}
