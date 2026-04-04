"""Tool registry — module-level singleton."""
from __future__ import annotations
from typing import Callable, Dict, Optional

_registry: Optional[Dict[str, Callable]] = None

def get_registry() -> Dict[str, Callable]:
    global _registry
    if _registry is None:
        _registry = _build()
    return _registry

def invalidate_registry() -> None:
    global _registry
    _registry = None

def _build() -> Dict[str, Callable]:
    from src.config import Config
    cfg = Config.get()
    registry: Dict[str, Callable] = {}

    if cfg.enable_web_search:
        from src.tools.web_search_tool import web_search
        registry["web_search"] = web_search

    if cfg.enable_wikipedia_search:
        from src.tools.wikipedia_tool import wikipedia_search
        registry["wikipedia_search"] = wikipedia_search

    if cfg.enable_web_fetch:
        from src.tools.curl_tool import curl_fetch
        registry["curl"] = curl_fetch

    if cfg.enable_code_execution:
        from src.tools.shell_tool import run_shell_command, watch_task_logs
        registry["run_shell_command"] = run_shell_command
        registry["watch_task_logs"] = watch_task_logs
        from src.tools.code_runner_tool import run_python
        registry["run_python"] = run_python

    async def list_workspace_tool(query: str = "") -> str:
        from src.tools.workspace import get_workspace_path, list_workspace
        return list_workspace(get_workspace_path(cfg.workspace_path), depth=3)

    registry["list_workspace"] = list_workspace_tool

    # Memory tools
    async def save_memory_tool(key: str, value: str, pinned: bool = False) -> str:
        from src.db.chat_store import save_rika_memory
        if not key:
            return "Error: 'key' is required."
        await save_rika_memory(0, key, value, "memory", pinned=bool(pinned))
        return f"Memory saved: {key}" + (" (pinned)" if pinned else "")

    registry["save_memory"] = save_memory_tool

    async def get_memories_tool() -> str:
        from src.db.chat_store import get_pinned_memories, list_skill_names
        pinned = await get_pinned_memories(0)
        skills = await list_skill_names(0)
        result = []
        if pinned:
            result.append("PINNED MEMORIES:\n" + "\n".join(f"  {k}: {v}" for k, v in pinned.items()))
        if skills:
            result.append("SKILLS:\n" + "\n".join(f"  {s}" for s in skills))
        return "\n\n".join(result) if result else "No memories or skills stored."

    registry["get_memories"] = get_memories_tool

    async def save_skill_tool(name: str, code: str) -> str:
        from src.db.chat_store import save_skill
        if not name:
            return "Error: 'name' is required."
        await save_skill(0, name, code)
        return f"Skill saved: {name}"

    registry["save_skill"] = save_skill_tool

    async def use_skill_tool(skill_name: str) -> str:
        from src.db.chat_store import get_skill
        code = await get_skill(0, skill_name)
        if code is None:
            return f"Error: Skill '{skill_name}' not found. Use get_memories to list available skills."
        return f"Skill '{skill_name}' loaded:\n{code}"

    registry["use_skill"] = use_skill_tool

    async def delegate_task(query: str) -> str:
        """Spawn a research sub-agent for a specific query."""
        from src.agents.agent_factory import ConcreteAgent
        from src.agents.agent_models import AgentSpec
        from src.providers.provider_pool import get_pool
        
        try:
            agent = ConcreteAgent(AgentSpec(
                name="delegate",
                system_prompt="You are a specialized research assistant. Focus on gathering information and providing clear, concise answers.",
                tools=["web_search", "wikipedia_search", "curl", "run_shell_command"],
            ))
            result = await agent.run(0, query)
            return f"Delegated task completed:\n{result.get('output', str(result))}"
        except Exception as e:
            return f"Delegated task failed: {str(e)}"

    registry["delegate_task"] = delegate_task

    # File delivery tool — returns a marker for the orchestration layer to handle
    async def send_file_tool(path: str, caption: str = "") -> str:
        """Signal to send a file. The orchestration layer handles actual delivery."""
        if not path:
            return "Error: 'path' is required."
        return f"__SEND_FILE__:{path}:{caption}"

    registry["send_file"] = send_file_tool

    # File write tool — write text/JSON/code to workspace files
    async def write_file_tool(path: str, content: str, mode: str = "w") -> str:
        """Write content to a file in the workspace. Use for saving research data, code, configs, etc."""
        from pathlib import Path
        from src.tools.workspace import get_workspace_path
        
        if not path:
            return "Error: 'path' is required."
        if not content:
            return "Error: 'content' is required."
        
        workspace = get_workspace_path(cfg.workspace_path)
        safe_path = path.lstrip("/").replace("..", "")
        full_path = (workspace / safe_path).resolve()
        
        # Security: only allow files inside workspace
        if not str(full_path).startswith(str(workspace)):
            return "Error: path traversal not allowed."
        
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, mode, encoding="utf-8") as f:
                f.write(content)
            return f"File written: {safe_path} ({len(content)} bytes)"
        except Exception as e:
            return f"Error writing file: {str(e)}"

    registry["write_file"] = write_file_tool

    # File read tool — read text/JSON/code from workspace files
    async def read_file_tool(path: str, max_lines: int = 200) -> str:
        """Read content from a file in the workspace. Use for analyzing saved data, code, configs, etc."""
        from pathlib import Path
        from src.tools.workspace import get_workspace_path
        
        if not path:
            return "Error: 'path' is required."
        
        workspace = get_workspace_path(cfg.workspace_path)
        safe_path = path.lstrip("/").replace("..", "")
        full_path = (workspace / safe_path).resolve()
        
        # Security: only allow files inside workspace
        if not str(full_path).startswith(str(workspace)):
            return "Error: path traversal not allowed."
        
        if not full_path.exists():
            return f"Error: file not found: {safe_path}"
        
        if full_path.stat().st_size > 1024 * 1024:  # 1MB limit
            return "Error: file too large (>1MB). Use shell command to read large files."
        
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            if len(lines) > max_lines:
                preview = "".join(lines[:max_lines])
                return f"File: {safe_path} (showing first {max_lines} of {len(lines)} lines):\n{preview}\n\n[... truncated, use shell 'tail' or 'head' for more ...]"
            
            return f"File: {safe_path}\n{''.join(lines)}"
        except Exception as e:
            return f"Error reading file: {str(e)}"

    registry["read_file"] = read_file_tool

    return registry

def build_registry(config=None) -> Dict[str, Callable]:
    return get_registry()
