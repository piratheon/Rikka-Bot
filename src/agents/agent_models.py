from pydantic import BaseModel
from typing import List, Dict, Literal


class AgentSpec(BaseModel):
    id: str
    name: str
    role: str
    system_prompt: str
    tools: List[str] = []
    output_schema: Dict = {}
    depends_on: List[str] = []
    model_preference: Literal["fast", "smart"] = "smart"


class TaskPlan(BaseModel):
    reasoning: str
    agents: List[AgentSpec] = []
    final_synthesis_prompt: str | None = None
