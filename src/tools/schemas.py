"""Tool schemas — JSON Schema definitions for every tool.

Used by providers that support function calling (Groq, OpenRouter, Ollama,
Gemini) to produce structured tool calls instead of free-text "TOOL: ..." output.

Each schema has:
  - name: matches the key in the tool registry
  - description: natural language explanation for the LLM
  - parameters: JSON Schema object (OpenAI function-calling format)

Providers convert these to their native format:
  - OpenAI-compatible (Groq, OpenRouter, Ollama): used as-is
  - Gemini: converted via to_gemini_declaration()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    required_params: List[str] = field(default_factory=list)

    def to_openai(self) -> Dict[str, Any]:
        """OpenAI / Groq / OpenRouter / Ollama function calling format."""
        params = dict(self.parameters)
        if self.required_params:
            params["required"] = self.required_params
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }

    def to_gemini(self) -> Dict[str, Any]:
        """Gemini FunctionDeclaration format (via genai SDK)."""
        try:
            from google.genai import types

            props = {}
            for pname, pschema in self.parameters.get("properties", {}).items():
                ptype = pschema.get("type", "string").upper()
                props[pname] = types.Schema(
                    type=ptype,
                    description=pschema.get("description", ""),
                )
            return types.FunctionDeclaration(
                name=self.name,
                description=self.description,
                parameters=types.Schema(
                    type="OBJECT",
                    properties=props,
                    required=self.required_params or [],
                ),
            )
        except ImportError:
            return {"name": self.name, "description": self.description}


def _str_param(description: str, required: bool = True) -> Dict[str, Any]:
    return {"type": "string", "description": description}


def _int_param(description: str, default: Optional[int] = None) -> Dict[str, Any]:
    p: Dict[str, Any] = {"type": "integer", "description": description}
    if default is not None:
        p["default"] = default
    return p


# ---------------------------------------------------------------------------
# Tool schema registry
# ---------------------------------------------------------------------------

ALL_SCHEMAS: List[ToolSchema] = [

    ToolSchema(
        name="web_search",
        description=(
            "Search the web using DuckDuckGo. Returns a list of results with "
            "title, URL, and snippet. Use for current events, recent data, or "
            "anything not in your training knowledge."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": _str_param("The search query string."),
                "max_results": _int_param("Maximum number of results to return.", default=5),
            },
        },
        required_params=["query"],
    ),

    ToolSchema(
        name="wikipedia_search",
        description=(
            "Search Wikipedia and return a detailed summary of the most relevant article. "
            "Best for well-established factual topics, historical events, and definitions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": _str_param("The topic or subject to look up on Wikipedia."),
            },
        },
        required_params=["query"],
    ),

    ToolSchema(
        name="curl",
        description=(
            "Fetch the text content of any URL. Strips HTML tags and returns readable text. "
            "Use to read documentation, articles, APIs, or any web page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": _str_param("The full URL to fetch, including https://."),
            },
        },
        required_params=["url"],
    ),

    ToolSchema(
        name="run_shell_command",
        description=(
            "Execute a shell command on the host system. "
            "Working directory is the agent workspace (~/.Rika-Workspace). "
            "Use for file operations, system info, package management, git, and scripting. "
            "Dangerous commands (rm -rf /, fork bombs, disk wipes) are blocked automatically. "
            "For medium-risk commands blocked by the security filter, prefix with 'CONFIRM: '."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": _str_param(
                    "The shell command to execute. "
                    "Prefix with 'CONFIRM: ' to override a medium-severity security warning."
                ),
            },
        },
        required_params=["command"],
    ),

    ToolSchema(
        name="run_python",
        description=(
            "Execute Python code in an isolated sandbox. "
            "Returns stdout, stderr, and any return value. "
            "Use for calculations, data processing, and algorithm testing. "
            "The sandbox level (none/process/docker) is configured by the server admin."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": _str_param("Python code to execute."),
                "timeout_seconds": _int_param("Maximum execution time in seconds.", default=30),
            },
        },
        required_params=["code"],
    ),

    ToolSchema(
        name="send_file",
        description=(
            "Send a file from the agent workspace to the user in the chat. "
            "Use this when you create a file the user needs to download: "
            "scripts, reports, generated code, analysis output, etc. "
            "ONLY files inside ~/.Rika-Workspace can be sent — never server system files. "
            "The path must be relative to the workspace root, e.g. 'report.py' or 'output/data.csv'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": _str_param(
                    "Path to the file relative to the workspace root. "
                    "Example: 'analysis.py', 'reports/summary.md', 'scripts/deploy.sh'"
                ),
                "caption": _str_param(
                    "Short description of the file shown below it in Telegram. Optional."
                ),
            },
        },
        required_params=["path"],
    ),

    ToolSchema(
        name="list_workspace",
        description=(
            "List all files and directories in the agent workspace (~/.Rika-Workspace). "
            "Use to check what files exist before reading or sending them."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": _str_param("Optional filter string. Leave empty to list everything.", ),
            },
        },
        required_params=[],
    ),

    ToolSchema(
        name="save_memory",
        description=(
            "Persist a key-value pair to long-term memory. "
            "Use to remember important facts about the user, their preferences, "
            "project details, or any information needed across conversations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "key": _str_param("A short descriptive key, e.g. 'user_language', 'project_name'."),
                "value": _str_param("The value to store. Can be any text."),
            },
        },
        required_params=["key", "value"],
    ),

    ToolSchema(
        name="get_memories",
        description="Retrieve all stored memories and skills for the current user.",
        parameters={"type": "object", "properties": {}},
        required_params=[],
    ),

    ToolSchema(
        name="save_skill",
        description=(
            "Store a reusable skill or script in memory. "
            "Use to remember code snippets, workflows, or procedures the user wants to reuse."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": _str_param("A short name for the skill."),
                "code": _str_param("The skill code, script, or description."),
            },
        },
        required_params=["name", "code"],
    ),

    ToolSchema(
        name="delegate_task",
        description=(
            "Spawn a specialized research sub-agent to handle a specific sub-task. "
            "The sub-agent has access to web_search, curl, wikipedia_search, and run_shell_command. "
            "Use for tasks that require independent research while you handle other work."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": _str_param("A clear, self-contained description of the task for the sub-agent."),
            },
        },
        required_params=["query"],
    ),
]

# Fast lookup by name
SCHEMA_MAP: Dict[str, ToolSchema] = {s.name: s for s in ALL_SCHEMAS}


def get_schemas_for_tools(tool_names: List[str]) -> List[ToolSchema]:
    """Return ToolSchema objects for the given tool names (in registry order)."""
    return [SCHEMA_MAP[n] for n in tool_names if n in SCHEMA_MAP]


def get_all_schemas() -> List[ToolSchema]:
    return ALL_SCHEMAS
