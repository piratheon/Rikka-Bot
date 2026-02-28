from typing import Dict

TOOL_REGISTRY: Dict[str, object] = {}


def build_registry(config) -> Dict[str, object]:
    registry = {}
    
    # Core Tools
    if getattr(config, "enable_wikipedia_search", True):
        from src.tools.wikipedia_tool import wikipedia_search
        registry["wikipedia_search"] = wikipedia_search
        
    from src.tools.curl_tool import curl_fetch
    registry["curl"] = curl_fetch
    
    # Memory Tools (Always available for Rikka)
    from src.db.chat_store import save_rikka_memory, get_rikka_memories
    
    async def save_memory_tool(arg: str):
        # Expected arg format: "key | value"
        if " | " not in arg: return "Error: Use format 'key | value'"
        k, v = arg.split(" | ", 1)
        # Note: user_id needs to be handled via context or passed. 
        # For simplicity in registry, we wrap it or assume user_id is injected by Agent.
        # Actually, let's just register the functions and handle injection in ConcreteAgent.
        return f"Save memory function for {k}"

    registry["save_memory"] = save_memory_tool
    registry["get_memories"] = lambda _: "Get memories function"
    
    if getattr(config, "enable_code_execution", False):
        from src.tools.code_runner_tool import run_python
        registry["run_python"] = run_python
        
    return registry
