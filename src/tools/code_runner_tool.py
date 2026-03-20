<<<<<<< HEAD
import asyncio
import sys
import io
from typing import Dict, Any

async def run_python(code: str, timeout_seconds: int = 5) -> Dict[str, Any]:
    """Execute Python code in a RestrictedPython sandbox if available.

    Returns a dict with keys: `stdout`, `result` (repr), and `error` if any.
    If `RestrictedPython` is not installed, returns an error message advising installation.

    This is intentionally conservative: no networking, file I/O, or imports are allowed.
    """
    if not code:
        return {"error": "no code provided"}

    try:
        from RestrictedPython import compile_restricted_exec
        from RestrictedPython.Guards import safe_builtins
    except Exception as e:
        return {"error": "RestrictedPython not installed. Install with: pip install RestrictedPython"}

    # Prepare restricted environment
    builtins = dict(safe_builtins)
    # Remove potentially dangerous builtins if present
    for banned in ("open", "eval", "exec", "compile", "__import__"):
        builtins.pop(banned, None)

    globals_dict = {
        "__builtins__": builtins,
        "_print_": lambda *args, **kwargs: None,  # disable internal print; we capture via stdout
    }
    locals_dict = {}

    # Capture stdout
    stdout_buf = io.StringIO()

    def _run():
        try:
            code_obj = compile_restricted_exec(code)
            # Redirect stdout in-thread
            old_stdout = sys.stdout
            try:
                sys.stdout = stdout_buf
                exec(code_obj, globals_dict, locals_dict)
            finally:
                sys.stdout = old_stdout
            return {"stdout": stdout_buf.getvalue(), "result": repr(locals_dict.get("result", None))}
        except Exception as ex:
            return {"stdout": stdout_buf.getvalue(), "error": f"{type(ex).__name__}: {ex}"}

    loop = asyncio.get_running_loop()
    try:
        res = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=timeout_seconds)
        return res
    except asyncio.TimeoutError:
        return {"error": "execution_timeout"}
    except Exception as e:
        return {"error": str(e)}
=======
"""Code runner — delegates to sandbox.py at the configured isolation level."""
from __future__ import annotations
import asyncio
from typing import Any, Dict, Optional
from src.utils.logger import logger

async def run_python(code: str, timeout_seconds: int = 30,
                     workspace: Optional[str] = None) -> Dict[str, Any]:
    """Execute Python code at the configured sandbox isolation level."""
    from src.config import Config
    from src.tools.sandbox import run_sandboxed
    from src.tools.workspace import get_workspace_path
    cfg = Config.get()
    level = getattr(cfg, "sandbox_level", 0)
    ws = workspace or str(get_workspace_path(cfg.workspace_path))
    result = await run_sandboxed(code, level=level, timeout=int(timeout_seconds), workspace=ws)
    # Format for agent consumption
    if result.get("error") and not result.get("stdout"):
        return {"error": result["error"], "stdout": "", "exit_code": result.get("exit_code", 1)}
    return result
>>>>>>> 7599a86 (Upgrade: From rika-bot to rika-agent)
