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

    async def delegate_task(query: str) -> str:
        return f"[delegate_task]: {query}"

    registry["delegate_task"] = delegate_task
    return registry

def build_registry(config=None) -> Dict[str, Callable]:
    return get_registry()
