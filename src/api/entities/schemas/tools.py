from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, validator

# -----------------------------------------------------------------------------
# ToolFunction Schema
# -----------------------------------------------------------------------------
class ToolFunction(BaseModel):
    function: Optional[Dict[str, Any]] = Field(
        None,
        description="A dictionary containing function details (name, description, and parameters).",
        example={
            "name": "code_interpreter",
            "description": "Executes Python code in a sandbox environment and returns JSON output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"}
                },
                "required": ["code"]
            }
        }
    )

    @validator('function', pre=True, always=True)
    def parse_function(cls, v):
        if isinstance(v, dict):
            if 'name' in v and 'description' in v:
                return v
            elif 'function' in v:
                return v['function']
        raise ValueError("Invalid function format; expected a dictionary with function details.")

    model_config = ConfigDict(from_attributes=True)

# -----------------------------------------------------------------------------
# Tool Base Schema
# -----------------------------------------------------------------------------
class Tool(BaseModel):
    id: Optional[str] = Field(
        None,
        description="Unique identifier for the tool.",
        example="tool_123456"
    )
    type: str = Field(
        ...,
        description="Type of the tool.",
        example="code_interpreter"
    )
    name: Optional[str] = Field(
        None,
        description="Name of the tool.",
        example="Code Interpreter"
    )
    function: Optional[ToolFunction] = Field(
        None,
        description="Function details for the tool."
    )

    model_config = ConfigDict(from_attributes=True)

# -----------------------------------------------------------------------------
# ToolRead Schema (for responses)
# -----------------------------------------------------------------------------
class ToolRead(Tool):
    @validator('function', pre=True, always=True)
    def parse_function(cls, v):
        # If already a dictionary, return it directly.
        if isinstance(v, dict):
            return v
        # If it's a ToolFunction instance, convert to dict.
        elif isinstance(v, ToolFunction):
            return v.dict()
        elif v is None:
            return None
        else:
            raise ValueError("Invalid function format; expected a dictionary or ToolFunction instance.")

    model_config = ConfigDict(from_attributes=True)

# -----------------------------------------------------------------------------
# ToolCreate Schema (for tool creation requests)
# -----------------------------------------------------------------------------
class ToolCreate(BaseModel):
    name: str = Field(
        ...,
        description="Name of the tool.",
        example="Code Interpreter"
    )
    type: str = Field(
        ...,
        description="Type of the tool.",
        example="code_interpreter"
    )
    function: Optional[ToolFunction] = Field(
        None,
        description="Function details for the tool."
    )

    @validator('function', pre=True, always=True)
    def parse_function(cls, v):
        if isinstance(v, ToolFunction):
            return v
        if isinstance(v, dict):
            if 'function' in v:
                return ToolFunction(function=v['function'])
            return ToolFunction(**v)
        return None

    model_config = ConfigDict(from_attributes=True)

# -----------------------------------------------------------------------------
# ToolUpdate Schema (for updating tool details)
# -----------------------------------------------------------------------------
class ToolUpdate(BaseModel):
    type: Optional[str] = Field(
        None,
        description="Updated type of the tool.",
        example="code_interpreter"
    )
    name: Optional[str] = Field(
        None,
        description="Updated name of the tool.",
        example="Code Interpreter"
    )
    function: Optional[ToolFunction] = Field(
        None,
        description="Updated function details for the tool."
    )

    model_config = ConfigDict(from_attributes=True)

# -----------------------------------------------------------------------------
# ToolList Schema (for listing tools)
# -----------------------------------------------------------------------------
class ToolList(BaseModel):
    tools: List[ToolRead] = Field(
        ...,
        description="List of tool definitions."
    )

    model_config = ConfigDict(from_attributes=True)
