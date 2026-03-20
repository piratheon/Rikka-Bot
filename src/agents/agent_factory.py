"""ConcreteAgent — function-calling ReAct loop with structured responses.

Phase 1 upgrade: uses JSON function calling via request_with_tools() instead
of regex parsing of "TOOL: ..." text. Falls back to text protocol if all
providers fail or return non-tool responses.
"""
from __future__ import annotations
import asyncio, json, re
from typing import Any, Dict, List, Optional
from src.agents.agent_models import AgentSpec
from src.agents.base_agent import BaseAgent
from src.config import Config
from src.providers.base_provider import StructuredResponse, ToolCall
from src.providers.provider_pool import get_pool
from src.tools.registry import get_registry
from src.utils.logger import logger

MAX_TOOL_TURNS = 8
MAX_AGENT_DEPTH = 2

# ---------------------------------------------------------------------------
# Tool executor (standalone — used by orchestration loop too)
# ---------------------------------------------------------------------------

async def execute_tool(tool_name: str, arguments: Dict[str, Any], user_id: int,
                       depth: int = 0, system_prompt: str = "", bubble=None) -> str:
    """Execute a tool by name with structured arguments dict."""
    from src.db.chat_store import get_rika_memories, save_rika_memory

    # Memory tools
    if tool_name == "save_memory":
        k, v = arguments.get("key", ""), arguments.get("value", "")
        if not k: return "Error: 'key' is required."
        await save_rika_memory(user_id, k, v, "memory")
        return f"Memory saved: {k}"

    if tool_name == "save_skill":
        k, v = arguments.get("name", ""), arguments.get("code", "")
        if not k: return "Error: 'name' is required."
        await save_rika_memory(user_id, k, v, "skill")
        return f"Skill saved: {k}"

    if tool_name == "get_memories":
        mems = await get_rika_memories(user_id, "memory")
        skills = await get_rika_memories(user_id, "skill")
        return "MEMORIES:\n" + json.dumps(mems, indent=2) + "\n\nSKILLS:\n" + json.dumps(skills, indent=2)

    # Delegation
    if tool_name == "delegate_task":
        if depth >= MAX_AGENT_DEPTH: return f"Error: max depth ({MAX_AGENT_DEPTH}) reached."
        query = arguments.get("query", "")
        sub_spec = AgentSpec(id="sub_research", name="ResearchAgent", role="Researcher",
                             system_prompt=system_prompt,
                             tools=["web_search", "curl", "wikipedia_search", "run_shell_command"])
        sub = ConcreteAgent(sub_spec, bubble=bubble, depth=depth + 1)
        res = await sub.run({"user_id": user_id, "message": query, "full_context": query})
        return res.get("output", "No result.")

    # send_file is handled specially by the bot layer; here we just validate and return a signal
    if tool_name == "send_file":
        path = arguments.get("path", "").strip()
        caption = arguments.get("caption", "")
        return f"__SEND_FILE__:{path}:{caption}"

    # Registry tools
    registry = get_registry()
    tool_fn = registry.get(tool_name)
    if tool_fn is None:
        return f"Error: tool '{tool_name}' not found."

    try:
        # Special handling for tools with known argument shapes
        if tool_name == "run_shell_command":
            cmd = arguments.get("command", "")
            raw = await tool_fn(cmd, user_id=user_id) if asyncio.iscoroutinefunction(tool_fn) else tool_fn(cmd, user_id=user_id)
        elif tool_name == "run_python":
            code = arguments.get("code", "")
            timeout = arguments.get("timeout_seconds", 30)
            raw = await tool_fn(code, timeout_seconds=int(timeout)) if asyncio.iscoroutinefunction(tool_fn) else tool_fn(code)
        elif tool_name == "watch_task_logs":
            raw = await tool_fn(arguments.get("file_path", ""), arguments.get("timeout", "30"))
        elif len(arguments) == 0:
            raw = await tool_fn("") if asyncio.iscoroutinefunction(tool_fn) else tool_fn("")
        elif len(arguments) == 1:
            val = next(iter(arguments.values()), "")
            raw = await tool_fn(str(val)) if asyncio.iscoroutinefunction(tool_fn) else tool_fn(str(val))
        else:
            # Pass as kwargs
            raw = await tool_fn(**{k: str(v) for k, v in arguments.items()}) if asyncio.iscoroutinefunction(tool_fn) else tool_fn(**{k: str(v) for k, v in arguments.items()})

        if isinstance(raw, dict):
            if raw.get("blocked"): return raw.get("message", "Command blocked by security policy.")
            parts = []
            if raw.get("stdout"): parts.append(f"stdout:\n{raw['stdout']}")
            if raw.get("stderr"): parts.append(f"stderr:\n{raw['stderr']}")
            if "exit_code" in raw: parts.append(f"exit_code: {raw['exit_code']}")
            if raw.get("cwd"): parts.append(f"cwd: {raw['cwd']}")
            if raw.get("error"): parts.append(f"error: {raw['error']}")
            return "\n".join(parts) or "Done."
        return str(raw)
    except Exception as exc:
        logger.error("tool_execution_failed", tool=tool_name, error=str(exc))
        return f"Error executing {tool_name}: {exc}"


# ---------------------------------------------------------------------------
# Text-protocol fallback parser (when function calling unavailable)
# ---------------------------------------------------------------------------

def _parse_text_tool_call(text: str):
    """Extract tool name and arguments from legacy 'TOOL: name | QUERY: ...' format."""
    match = re.search(r"TOOL:\s*([\w_]+)\s*\|?\s*QUERY:\s*(.*)", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip(), {"query": match.group(2).strip()}
    return None, None


# ---------------------------------------------------------------------------
# ConcreteAgent
# ---------------------------------------------------------------------------

class ConcreteAgent(BaseAgent):
    def __init__(self, spec: AgentSpec, bubble=None, depth: int = 0) -> None:
        self.spec = spec
        self.bubble = bubble
        self.depth = depth

    async def _get_tool_schemas(self):
        """Return ToolSchema objects for this agent's tool list."""
        from src.tools.schemas import get_schemas_for_tools, get_all_schemas
        if not self.spec.tools:
            return []
        # Add memory tools which are always available
        all_tools = list(self.spec.tools) + ["save_memory", "get_memories", "save_skill", "delegate_task"]
        return get_schemas_for_tools(all_tools)

    async def _request_structured(self, user_id: int, messages: list,
                                   schemas: list) -> StructuredResponse:
        cfg = Config.get()
        pool = get_pool()
        payload = {"model": cfg.default_model, "messages": messages}
        for provider in (cfg.default_provider_priority or ["gemini", "groq", "openrouter"]):
            try:
                resp = await pool.request_with_key_structured(user_id, provider, payload, schemas)
                return resp
            except Exception as exc:
                logger.warning("agent_provider_failed", provider=provider, error=str(exc))
        raise RuntimeError("All providers failed.")

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        cfg = Config.get()
        user_id = int(context.get("user_id", 0))
        message = context.get("message", "")
        full_context = context.get("full_context", message)

        from src.db.chat_store import get_rika_memories
        mems = await get_rika_memories(user_id, "memory")
        skills = await get_rika_memories(user_id, "skill")
        dep_outputs = {dep: context.get("results", {}).get(dep, {}).get("output", "N/A")
                       for dep in self.spec.depends_on}

        sys_msg = self.spec.system_prompt or cfg.system_prompt
        if mems: sys_msg += "\n\nMEMORIES:\n" + json.dumps(mems)
        if skills: sys_msg += "\n\nSKILLS:\n" + json.dumps(skills)
        if dep_outputs: sys_msg += "\n\nTEAMMATE CONTEXT:\n" + json.dumps(dep_outputs, indent=2)

        schemas = await self._get_tool_schemas() if self.spec.tools else []
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": f"Context: {full_context}\n\nTask: {message}"},
        ]
        tool_used: Optional[str] = None
        send_files: List[Dict] = []

        for _turn in range(MAX_TOOL_TURNS):
            try:
                response = await self._request_structured(user_id, messages, schemas)
            except Exception as exc:
                return {"id": self.spec.id, "output": f"Error: {exc}"}

            # Function calling path
            if response.has_tool_calls:
                tool_results = []
                for tc in response.tool_calls:
                    if self.bubble: self.bubble.update(self.spec.id, f"calling {tc.name}...")
                    result_str = await execute_tool(tc.name, tc.arguments, user_id,
                                                   depth=self.depth, system_prompt=sys_msg, bubble=self.bubble)
                    tool_used = tc.name
                    # Intercept file send signals
                    if result_str.startswith("__SEND_FILE__:"):
                        parts = result_str[len("__SEND_FILE__:"):].split(":", 1)
                        send_files.append({"path": parts[0], "caption": parts[1] if len(parts) > 1 else ""})
                        result_str = f"File queued for sending: {parts[0]}"
                    tool_results.append({"tool_call_id": tc.call_id, "name": tc.name, "content": result_str})

                # Add assistant turn with tool calls
                messages.append({"role": "assistant", "content": response.content or "",
                                  "tool_calls": [{"id": tc.call_id, "type": "function",
                                                   "function": {"name": tc.name,
                                                                "arguments": json.dumps(tc.arguments)}}
                                                  for tc in response.tool_calls]})
                # Add tool results
                for tr in tool_results:
                    messages.append({"role": "tool", "tool_call_id": tr["tool_call_id"],
                                     "content": tr["content"]})
                continue

            # Text-protocol fallback
            if not response.has_tool_calls and schemas:
                t_name, t_args = _parse_text_tool_call(response.content)
                if t_name:
                    if self.bubble: self.bubble.update(self.spec.id, f"using {t_name}...")
                    result_str = await execute_tool(t_name, t_args or {}, user_id,
                                                   depth=self.depth, system_prompt=sys_msg)
                    tool_used = t_name
                    if result_str.startswith("__SEND_FILE__:"):
                        parts = result_str[len("__SEND_FILE__:"):].split(":", 1)
                        send_files.append({"path": parts[0], "caption": parts[1] if len(parts) > 1 else ""})
                        result_str = f"File queued: {parts[0]}"
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": f"Result:\n{result_str}\n\nContinue."})
                    continue

            # Final response
            return {
                "id": self.spec.id,
                "output": response.content.strip(),
                "tool_used": tool_used,
                "send_files": send_files,
            }

        # Turn limit — synthesize
        try:
            final = await self._request_structured(user_id, messages, [])
            return {"id": self.spec.id, "output": final.content, "tool_used": tool_used, "send_files": send_files}
        except Exception as exc:
            return {"id": self.spec.id, "output": f"Error: {exc}", "send_files": send_files}


class AgentFactory:
    @staticmethod
    def create(spec: AgentSpec, bubble=None, depth: int = 0) -> BaseAgent:
        return ConcreteAgent(spec, bubble=bubble, depth=depth)
