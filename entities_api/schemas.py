from pydantic import BaseModel, Field, validator, ConfigDict
from typing import List, Optional, Dict, Any

class UserBase(BaseModel):
    id: str
    name: str

    model_config = ConfigDict(from_attributes=True)

class UserCreate(BaseModel):
    name: Optional[str] = "Anonymous User"

class UserRead(UserBase):
    pass

class UserUpdate(BaseModel):
    name: Optional[str] = None

class UserDeleteResponse(BaseModel):
    success: bool
    message: Optional[str] = None

class ThreadCreate(BaseModel):
    participant_ids: List[str] = Field(..., description="List of participant IDs")
    meta_data: Optional[Dict[str, Any]] = {}

class ThreadRead(BaseModel):
    id: str
    created_at: int
    meta_data: Dict[str, Any]
    object: str
    tool_resources: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)

class ThreadUpdate(BaseModel):
    participant_ids: Optional[List[str]] = None
    meta_data: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)

class ThreadParticipant(UserBase):
    pass

class ThreadReadDetailed(ThreadRead):
    participants: List[UserBase]

    model_config = ConfigDict(from_attributes=True)

class ThreadIds(BaseModel):
    thread_ids: List[str]

    model_config = ConfigDict(from_attributes=True)

class MessageCreate(BaseModel):
    content: str
    thread_id: str
    sender_id: str
    role: str = "user"
    meta_data: Optional[Dict[str, Any]] = {}

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "Hello, this is a test message.",
                "thread_id": "example_thread_id",
                "sender_id": "example_sender_id",
                "meta_data": {"key": "value"},
                "role": "user"
            }
        }
    )

class MessageRead(BaseModel):
    id: str
    assistant_id: Optional[str]
    attachments: List[Any]
    completed_at: Optional[int]
    content: str
    created_at: int
    incomplete_at: Optional[int]
    incomplete_details: Optional[Dict[str, Any]]
    meta_data: Dict[str, Any]
    object: str
    role: str
    run_id: Optional[str]
    status: Optional[str]
    thread_id: str
    sender_id: str

    model_config = ConfigDict(from_attributes=True)

class MessageUpdate(BaseModel):
    content: Optional[str]
    meta_data: Optional[Dict[str, Any]]
    status: Optional[str]

    model_config = ConfigDict(from_attributes=True)


# New schema for creating tool messages
class ToolMessageCreate(BaseModel):
    content: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "This is the content of the tool message."
            }
        }
    )

class ToolFunction(BaseModel):
    function: Optional[dict]  # Handle the nested 'function' structure

    @validator('function', pre=True, always=True)
    def parse_function(cls, v):
        if isinstance(v, dict) and 'name' in v and 'description' in v:
            return v  # Valid structure
        elif isinstance(v, dict) and 'function' in v:
            return v['function']  # Extract nested function dict
        raise ValueError("Invalid function format")

class Tool(BaseModel):
    id: str
    type: str
    function: Optional[ToolFunction]

    model_config = ConfigDict(from_attributes=True)

class ToolCreate(BaseModel):
    type: str
    function: Optional[ToolFunction]

    @validator('function', pre=True, always=True)
    def parse_function(cls, v):
        if isinstance(v, dict) and 'function' in v:
            # If it's nested, pass only the inner function dictionary
            return ToolFunction(function=v['function'])
        return ToolFunction(**v)

class ToolRead(Tool):
    @validator('function', pre=True, always=True)
    def parse_function(cls, v):
        if isinstance(v, dict):
            return ToolFunction(**v)
        elif v is None:
            return None
        else:
            raise ValueError("Invalid function format")

    model_config = ConfigDict(from_attributes=True)

class ToolUpdate(BaseModel):
    type: Optional[str] = None
    function: Optional[ToolFunction] = None

class ToolList(BaseModel):
    tools: List[ToolRead]

    model_config = ConfigDict(from_attributes=True)

class RunCreate(BaseModel):
    id: str
    assistant_id: str
    cancelled_at: Optional[int] = None
    completed_at: Optional[int] = None
    created_at: int
    expires_at: int
    failed_at: Optional[int] = None
    incomplete_details: Optional[Dict[str, Any]] = None
    instructions: str
    last_error: Optional[str] = None
    max_completion_tokens: Optional[int] = 1000
    max_prompt_tokens: Optional[int] = 500
    meta_data: Dict[str, Any] = {}
    model: str = "gpt-4"
    object: str = "run"
    parallel_tool_calls: bool = False
    required_action: Optional[str] = None
    response_format: str = "text"
    started_at: Optional[int] = None
    status: str = "pending"
    thread_id: str
    tool_choice: str = "none"
    tools: List[Tool] = []
    truncation_strategy: Dict[str, Any] = {}
    usage: Optional[Any] = None
    temperature: float = 0.7
    top_p: float = 0.9
    tool_resources: Dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)

class Run(BaseModel):
    id: str
    assistant_id: str
    cancelled_at: Optional[int]
    completed_at: Optional[int]
    created_at: int
    expires_at: int
    failed_at: Optional[int]
    incomplete_details: Optional[Dict[str, Any]]
    instructions: str
    last_error: Optional[str]
    max_completion_tokens: Optional[int]
    max_prompt_tokens: Optional[int]
    meta_data: Dict[str, Any]
    model: str
    object: str
    parallel_tool_calls: bool
    required_action: Optional[str]
    response_format: str
    started_at: Optional[int]
    status: str
    thread_id: str
    tool_choice: str
    tools: List[Tool]
    truncation_strategy: Dict[str, Any]
    usage: Optional[Any]
    temperature: float
    top_p: float
    tool_resources: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)

class RunStatusUpdate(BaseModel):
    status: str

class AssistantCreate(BaseModel):
    user_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    model: str
    instructions: Optional[str] = None
    tools: Optional[List[Tool]] = None
    meta_data: Optional[Dict[str, Any]] = {}
    top_p: Optional[float] = 1.0
    temperature: Optional[float] = 1.0
    response_format: Optional[str] = "auto"

class AssistantRead(BaseModel):
    id: str
    user_id: str
    object: str
    created_at: int
    name: str
    description: Optional[str]
    model: str
    instructions: Optional[str]
    meta_data: Optional[Dict[str, Any]] = None
    top_p: float
    temperature: float
    response_format: str

    model_config = ConfigDict(from_attributes=True)

class AssistantUpdate(BaseModel):
    name: Optional[str]
    description: Optional[str]
    model: Optional[str]
    instructions: Optional[str]
    tools: Optional[List[Tool]]
    meta_data: Optional[Dict[str, Any]]
    top_p: Optional[float]
    temperature: Optional[float]

    model_config = ConfigDict(from_attributes=True)
