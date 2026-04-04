"""ConcreteAgent — function-calling ReAct loop with token-efficient context.

Token efficiency changes:
- Memories: pinned (always) + semantic retrieval (top-4 relevant) only.
  No more full JSON dump of all memories on every call.
- Skills: lazy-loaded via use_skill tool. Never injected into system prompt.
  Saves 100-400 tokens per call when skills exist.
- Runtime system message is built once per run, not per turn.
- Skill names listed in use_skill tool description so agent knows what exists.
"""
from __future__ import annotations

import asyncio
import json
import re
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
# Context builder — token-efficient
# ---------------------------------------------------------------------------

async def build_system_context(
    user_id: int,
    base_system_prompt: str,
    current_message: str,
    dep_outputs: Optional[Dict[str, str]] = None,
) -> str:
    """Build a token-efficient system message.

    Injects:
    - base_system_prompt (soul + tools + mandates)
    - pinned memories (max 5, always relevant)
    - semantically relevant memories (top 4 for this specific message)
    - skill names only (not skill content — lazy-loaded via use_skill tool)
    - dependency outputs from teammate agents (if any)

    Does NOT inject:
    - all memories as a JSON dump
    - all skills as a JSON dump
    - action logs (those belong in the watcher context, not here)
    """
    from src.db.chat_store import (
        get_pinned_memories,
        get_relevant_memories,
        list_skill_names,
    )

    parts = [base_system_prompt]

    # Pinned memories — always injected, zero retrieval cost
    pinned = await get_pinned_memories(user_id)
    if pinned:
        pinned_lines = "\n".join(f"  {k}: {v}" for k, v in pinned.items())
        parts.append(f"[PINNED CONTEXT]\n{pinned_lines}")

    # Semantically relevant memories — retrieved for this specific message
    if current_message:
        relevant = await get_relevant_memories(user_id, current_message, limit=4)
        # Remove any that were already in pinned
        relevant = {k: v for k, v in relevant.items() if k not in pinned}
        if relevant:
            rel_lines = "\n".join(f"  {k}: {v}" for k, v in relevant.items())
            parts.append(f"[RELEVANT MEMORY]\n{rel_lines}")

    # Skill names only — agent calls use_skill to load content
    skill_names = await list_skill_names(user_id)
    if skill_names:
        parts.append(
            f"[AVAILABLE SKILLS] (call use_skill to load any of these):\n"
            + ", ".join(skill_names)
        )

    # Teammate context (multi-agent runs)
    if dep_outputs:
        non_empty = {k: v for k, v in dep_outputs.items() if v and v != "N/A"}
        if non_empty:
            parts.append("[TEAMMATE CONTEXT]\n" + json.dumps(non_empty, indent=2))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

async def execute_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    user_id: int,
    depth: int = 0,
    system_prompt: str = "",
    bubble=None,
) -> str:
    """Execute a tool by name with structured arguments dict."""
    from src.db.chat_store import (
        get_rika_memories, save_rika_memory,
        get_skill, list_skill_names, save_skill,
    )

    # Memory tools
    if tool_name == "save_memory":
        k = arguments.get("key", "")
        v = arguments.get("value", "")
        if not k:
            return "Error: 'key' is required."
        pinned = arguments.get("pinned", False)
        await save_rika_memory(user_id, k, v, "memory", pinned=bool(pinned))
        return f"Memory saved: {k}" + (" (pinned)" if pinned else "")

    if tool_name == "save_skill":
        k = arguments.get("name", "")
        v = arguments.get("code", "")
        if not k:
            return "Error: 'name' is required."
        await save_skill(user_id, k, v)
        return f"Skill saved: {k}"

    if tool_name == "get_memories":
        # Return pinned + top-10 recent, not full dump
        from src.db.chat_store import get_pinned_memories
        pinned = await get_pinned_memories(user_id)
        all_mems = await get_rika_memories(user_id, "memory")
        # Show pinned first, then a sample of others
        result = {}
        result.update(pinned)
        for k, v in all_mems.items():
            if k not in result:
                result[k] = v
            if len(result) >= 20:
                break
        skills = list(await list_skill_names(user_id))
        return (
            f"MEMORIES ({len(all_mems)} total, showing {len(result)}):\n"
            + json.dumps(result, indent=2)
            + f"\n\nSKILL NAMES ({len(skills)}):\n"
            + (", ".join(skills) if skills else "none")
        )

    # Skill lazy-load — the key innovation
    if tool_name == "use_skill":
        skill_name = arguments.get("skill_name", "").strip()
        if not skill_name:
            return "Error: 'skill_name' is required."
        content = await get_skill(user_id, skill_name)
        if content is None:
            available = await list_skill_names(user_id)
            return (
                f"Skill '{skill_name}' not found.\n"
                f"Available skills: {', '.join(available) if available else 'none'}"
            )
        return f"SKILL '{skill_name}':\n{content}"

    # Delegation
    if tool_name == "delegate_task":
        if depth >= MAX_AGENT_DEPTH:
            return f"Error: max depth ({MAX_AGENT_DEPTH}) reached."
        query = arguments.get("query", "")
        sub_spec = AgentSpec(
            id="sub_research",
            name="ResearchAgent",
            role="Specialized researcher",
            system_prompt=system_prompt,
            tools=["web_search", "curl", "wikipedia_search", "run_shell_command"],
        )
        sub = ConcreteAgent(sub_spec, bubble=bubble, depth=depth + 1)
        res = await sub.run({"user_id": user_id, "message": query, "full_context": query})
        return res.get("output", "No result.")

    # File send signal
    if tool_name == "send_file":
        path = arguments.get("path", "").strip()
        caption = arguments.get("caption", "")
        return f"__SEND_FILE__:{path}:{caption}"

    # Registry tools
    registry = get_registry()
    tool_fn = registry.get(tool_name)
    if tool_fn is None:
        return f"Error: tool '{tool_name}' not found."

    # Get timeout from config (only applies to tool execution, not reasoning)
    cfg = Config.get()
    tool_timeout = getattr(cfg, "tool_timeout_seconds", 10)

    try:
        # Execute tool with timeout (reasoning has no timeout)
        if tool_name == "run_shell_command":
            cmd = arguments.get("command") or arguments.get("query", "")
            if not cmd:
                return "Error: no command provided."
            raw = await asyncio.wait_for(
                tool_fn(cmd, user_id=user_id) if asyncio.iscoroutinefunction(tool_fn) else tool_fn(cmd, user_id=user_id),
                timeout=tool_timeout
            )
        elif tool_name == "run_python":
            code = arguments.get("code") or arguments.get("query", "")
            if not code:
                return "Error: no code provided."
            timeout = min(arguments.get("timeout_seconds", 30), tool_timeout * 2)  # Allow longer for code execution
            raw = await asyncio.wait_for(
                tool_fn(code, timeout_seconds=int(timeout)) if asyncio.iscoroutinefunction(tool_fn) else tool_fn(code),
                timeout=timeout + 5
            )
        elif tool_name == "watch_task_logs":
            raw = await asyncio.wait_for(
                tool_fn(arguments.get("file_path", ""), arguments.get("timeout", "30")),
                timeout=tool_timeout
            )
        elif tool_name == "write_file":
            raw = await asyncio.wait_for(
                tool_fn(
                    arguments.get("path", ""),
                    arguments.get("content", ""),
                    arguments.get("mode", "w"),
                ),
                timeout=tool_timeout
            )
        elif tool_name == "read_file":
            raw = await asyncio.wait_for(
                tool_fn(arguments.get("path", ""), arguments.get("max_lines", 200)),
                timeout=tool_timeout
            )
        elif len(arguments) == 0:
            raw = await asyncio.wait_for(
                tool_fn("") if asyncio.iscoroutinefunction(tool_fn) else tool_fn(""),
                timeout=tool_timeout
            )
        elif len(arguments) == 1:
            val = next(iter(arguments.values()), "")
            raw = await asyncio.wait_for(
                tool_fn(str(val)) if asyncio.iscoroutinefunction(tool_fn) else tool_fn(str(val)),
                timeout=tool_timeout
            )
        else:
            kwargs = {k: str(v) for k, v in arguments.items()}
            raw = await asyncio.wait_for(
                tool_fn(**kwargs) if asyncio.iscoroutinefunction(tool_fn) else tool_fn(**kwargs),
                timeout=tool_timeout
            )

        if isinstance(raw, dict):
            if raw.get("blocked"):
                return raw.get("message", "Command blocked by security policy.")
            parts = []
            if raw.get("stdout"):
                parts.append(f"stdout:\n{raw['stdout']}")
            if raw.get("stderr"):
                parts.append(f"stderr:\n{raw['stderr']}")
            if "exit_code" in raw:
                parts.append(f"exit_code: {raw['exit_code']}")
            if raw.get("cwd"):
                parts.append(f"cwd: {raw['cwd']}")
            if raw.get("error"):
                parts.append(f"error: {raw['error']}")
            return "\n".join(parts) or "Done."
        return str(raw)

    except asyncio.TimeoutError:
        logger.error("tool_execution_timeout", tool=tool_name, timeout=tool_timeout)
        return f"Error: Tool '{tool_name}' timed out after {tool_timeout} seconds. For long-running tasks, use /watch to schedule as a background task."
    except Exception as exc:
        logger.error("tool_execution_failed", tool=tool_name, error=str(exc))
        return f"Error executing {tool_name}: {exc}"


# ---------------------------------------------------------------------------
# Text-protocol fallback
# ---------------------------------------------------------------------------

def _parse_text_tool_call(text: str):
    match = re.search(
        r"TOOL:\s*([\w_]+)\s*\|?\s*QUERY:\s*(.*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
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

    async def _get_tool_schemas(self, user_id: int):
        from src.db.chat_store import list_skill_names
        from src.tools.schemas import get_schemas_for_tools, SCHEMA_MAP

        if not self.spec.tools:
            return []
        # Core tools from spec
        base = list(self.spec.tools)
        # Always add memory tools + use_skill
        extras = ["save_memory", "get_memories", "save_skill", "use_skill", "delegate_task"]
        all_tools = base + [e for e in extras if e not in base]

        schemas = get_schemas_for_tools(all_tools)

        # Inject skill names into use_skill description dynamically
        skill_names = await list_skill_names(user_id)
        for s in schemas:
            if s.name == "use_skill" and skill_names:
                s = s  # mutable dataclass — update description
                object.__setattr__(
                    s, "description",
                    s.description + f" Available: {', '.join(skill_names[:20])}"
                )
        return schemas

    async def _request_structured(
        self, user_id: int, messages: list, schemas: list
    ) -> StructuredResponse:
        cfg = Config.get()
        pool = get_pool()
        payload = {"model": cfg.default_model, "messages": messages}
        for provider in (cfg.default_provider_priority or ["gemini", "groq", "openrouter"]):
            try:
                resp = await asyncio.wait_for(
                    pool.request_with_key_structured(user_id, provider, payload, schemas),
                    timeout=30.0,
                )
                return resp
            except asyncio.TimeoutError:
                logger.warning("agent_request_timeout", provider=provider)
                continue
            except Exception as exc:
                logger.warning("agent_provider_failed", provider=provider, error=str(exc))
        raise RuntimeError("All providers failed.")

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        cfg = Config.get()
        user_id = int(context.get("user_id", 0))
        message = context.get("message", "")
        full_context = context.get("full_context", message)
        dep_outputs = {
            dep: context.get("results", {}).get(dep, {}).get("output", "N/A")
            for dep in self.spec.depends_on
        }

        # Build token-efficient system message ONCE per run
        base_prompt = self.spec.system_prompt or cfg.system_prompt
        sys_msg = await build_system_context(
            user_id=user_id,
            base_system_prompt=base_prompt,
            current_message=message,
            dep_outputs=dep_outputs if dep_outputs else None,
        )

        schemas = await self._get_tool_schemas(user_id) if self.spec.tools else []
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
                    if self.bubble:
                        self.bubble.update(self.spec.id, f"calling {tc.name}...")
                    result_str = await execute_tool(
                        tc.name, tc.arguments, user_id,
                        depth=self.depth, system_prompt=sys_msg, bubble=self.bubble,
                    )
                    tool_used = tc.name
                    if result_str.startswith("__SEND_FILE__:"):
                        parts = result_str[len("__SEND_FILE__:"):].split(":", 1)
                        send_files.append({
                            "path": parts[0],
                            "caption": parts[1] if len(parts) > 1 else "",
                        })
                        result_str = f"File queued: {parts[0]}"
                    tool_results.append({
                        "tool_call_id": tc.call_id,
                        "name": tc.name,
                        "content": result_str,
                    })

                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": tc.call_id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in response.tool_calls
                    ],
                })
                for tr in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_call_id"],
                        "content": tr["content"],
                    })
                continue

            # Text-protocol fallback
            if schemas:
                t_name, t_args = _parse_text_tool_call(response.content)
                if t_name:
                    if self.bubble:
                        self.bubble.update(self.spec.id, f"using {t_name}...")
                    result_str = await execute_tool(
                        t_name, t_args or {}, user_id,
                        depth=self.depth, system_prompt=sys_msg,
                    )
                    tool_used = t_name
                    if result_str.startswith("__SEND_FILE__:"):
                        parts = result_str[len("__SEND_FILE__:"):].split(":", 1)
                        send_files.append({
                            "path": parts[0],
                            "caption": parts[1] if len(parts) > 1 else "",
                        })
                        result_str = f"File queued: {parts[0]}"
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": f"Result:\n{result_str}\n\nContinue.",
                    })
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
            return {
                "id": self.spec.id,
                "output": final.content,
                "tool_used": tool_used,
                "send_files": send_files,
            }
        except Exception as exc:
            return {"id": self.spec.id, "output": f"Error: {exc}", "send_files": send_files}


class AgentFactory:
    @staticmethod
    def create(spec: AgentSpec, bubble=None, depth: int = 0) -> BaseAgent:
        return ConcreteAgent(spec, bubble=bubble, depth=depth)
