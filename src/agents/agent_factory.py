from typing import Any, Dict, List
from .base_agent import BaseAgent
from .agent_models import AgentSpec
from src.providers.provider_pool import ProviderPool
from src.config import Config
from src.utils.logger import logger
from src.tools.registry import build_registry
import json
import re

class ConcreteAgent(BaseAgent):
    """A real agent that uses its spec to perform tasks and call tools."""
    
    def __init__(self, spec: AgentSpec, bubble: Any = None):
        self.spec = spec
        self.bubble = bubble
        self.config = Config.load()
        self.pool = ProviderPool()
        self.tool_registry = build_registry(self.config)

    async def _execute_tool(self, tool_name: str, query: str, user_id: int) -> str:
        """Executes a tool from the registry with context."""
        
        # Handle persistent memory tools specifically to inject user_id
        from src.db.chat_store import save_rikka_memory, get_rikka_memories
        
        if tool_name == "save_memory":
            if " | " not in query: return "Error: Use format 'key | value'"
            k, v = query.split(" | ", 1)
            await save_rikka_memory(user_id, k.strip(), v.strip(), 'memory')
            return f"Memory saved: {k}"
            
        if tool_name == "save_skill":
            if " | " not in query: return "Error: Use format 'name | description/code'"
            k, v = query.split(" | ", 1)
            await save_rikka_memory(user_id, k.strip(), v.strip(), 'skill')
            return f"Skill learned: {k}"

        if tool_name == "get_memories":
            mems = await get_rikka_memories(user_id, 'memory')
            skills = await get_rikka_memories(user_id, 'skill')
            out = "RIKKAS PERSISTENT MEMORIES:\n" + json.dumps(mems, indent=2)
            out += "\n\nRIKKAS PERSISTENT SKILLS:\n" + json.dumps(skills, indent=2)
            return out

        tool_fn = self.tool_registry.get(tool_name)
        if not tool_fn:
            return f"Error: Tool {tool_name} not found."
        
        try:
            import asyncio
            if asyncio.iscoroutinefunction(tool_fn):
                return await tool_fn(query)
            return tool_fn(query)
        except Exception as e:
            logger.error("tool_execution_failed", tool=tool_name, error=str(e))
            return f"Error executing {tool_name}: {e}"

    async def _request_with_failover(self, user_id: int, payload: dict) -> dict:
        """Helper to try multiple providers for an agent turn."""
        priorities = self.config.default_provider_priority or ["gemini", "groq", "openrouter"]
        for provider in priorities:
            try:
                return await self.pool.request_with_key(user_id, provider, payload)
            except Exception as e:
                logger.warning("agent_turn_provider_failed", provider=provider, error=str(e))
                continue
        raise RuntimeError("All providers failed for agent turn")

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the agent's task, potentially calling tools in a loop."""
        
        user_id = context.get("user_id", 0)
        message = context.get("message", "")
        full_context = context.get("full_context", message)
        results = context.get("results", {})
        
        # Load Rikkas memories/skills
        from src.db.chat_store import get_rikka_memories
        mems = await get_rikka_memories(user_id, 'memory')
        skills = await get_rikka_memories(user_id, 'skill')
        
        dependency_outputs = {
            dep: results.get(dep, {}).get("output", "Not available")
            for dep in self.spec.depends_on
        }

        system_msg = self.spec.system_prompt
        if mems: system_msg += "\n\nYOUR PERSISTENT MEMORIES:\n" + json.dumps(mems)
        if skills: system_msg += "\n\nYOUR PERSISTENT SKILLS:\n" + json.dumps(skills)
        if dependency_outputs: system_msg += "\n\nCONTEXT FROM TEAMMATES:\n" + json.dumps(dependency_outputs, indent=2)

        # Basic ReAct-style loop
        if self.spec.tools:
            tool_prompt = (
                f"{system_msg}\n\n"
                f"You have access to these tools: {', '.join(self.spec.tools)}, save_memory, get_memories, save_skill.\n"
                "If you need a tool, reply ONLY with: TOOL: tool_name | QUERY: your query\n"
                "Otherwise, provide your final response."
            )
            
            payload = {
                "model": self.config.default_model,
                "messages": [
                    {"role": "system", "content": tool_prompt},
                    {"role": "user", "content": f"Task Context: {full_context}\n\nSpecific Task: {message}"}
                ]
            }
            
            try:
                resp = await self._request_with_failover(user_id, payload)
                output = resp.get("output", "")
                
                # Robust parsing for TOOL: tool_name | QUERY: query
                match = re.search(r"TOOL:\s*(\w+)\s*\|\s*QUERY:\s*(.*)", output, re.IGNORECASE | re.DOTALL)
                if match:
                    t_name = match.group(1).strip()
                    t_query = match.group(2).strip()
                    
                    if self.bubble: self.bubble.update(self.spec.id, f"using {t_name}...")
                    tool_res = await self._execute_tool(t_name, t_query, user_id)
                    
                    # Final turn
                    final_payload = {
                        "model": self.config.default_model,
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": f"Task: {message}\n\nTool Result ({t_name}): {tool_res}\n\nFinal response:"}
                        ]
                    }
                    resp = await self._request_with_failover(user_id, final_payload)
                    return {"id": self.spec.id, "output": resp.get("output", ""), "tool_used": t_name}
                
                return {"id": self.spec.id, "output": output}
            except Exception as e:
                logger.error("agent_run_failed", agent_id=self.spec.id, error=str(e))

        # Standard non-tool path
        payload = {
            "model": self.config.default_model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Task Context: {full_context}\n\nSpecific Task: {message}"}
            ]
        }
        try:
            resp = await self._request_with_failover(user_id, payload)
            return {"id": self.spec.id, "output": resp.get("output", "")}
        except Exception as e:
            return {"id": self.spec.id, "output": f"Error: {str(e)}"}

class AgentFactory:
    @staticmethod
    def create(spec: AgentSpec, bubble: Any = None) -> BaseAgent:
        return ConcreteAgent(spec, bubble=bubble)
