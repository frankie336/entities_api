# entities_common/schemas/tools.py
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, validator


class ToolFunction(BaseModel):
    name: str = Field(..., description="Name of the function")
    description: str = Field(..., description="Function description")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="JSON Schema parameters")


class ToolCreate(BaseModel):
    type: str = Field(..., description="Tool type (must be 'function')")
    function: ToolFunction = Field(..., description="Function details")
    name: Optional[str] = Field(
        None, description="Auto-populated from function name"
    )  # For DB compatibility

    @validator("name", pre=True, always=True)
    def set_name_from_function(cls, v, values):
        if "function" in values and values["function"]:
            return values["function"].name
        return v

    @validator("type")
    def validate_type(cls, v):
        if v != "function":
            raise ValueError("Only 'function' type is supported")
        return v


class Tool(BaseModel):
    id: str
    type: str
    name: str  # Required from DB
    function: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class ToolRead(Tool):
    pass


class ToolUpdate(BaseModel):
    type: Optional[str] = None
    function: Optional[ToolFunction] = None
