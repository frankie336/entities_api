import time
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic import validator
from enum import Enum as PyEnum

import entities_api.models.models


class ProviderEnum(str, Enum):
    openai = "openai"
    deepseek = "deepseek"
    hyperbolic = "Hyperbolic"
    togetherai = "togetherai"
    local = "local"


class StreamRequest(BaseModel):
    provider: ProviderEnum = Field(..., description="The inference provider")
    model: str = Field(..., description="The model to use for inference")
    api_key: Optional[str] = Field(None, description="Optional API key for third-party providers")
    thread_id: str = Field(..., description="Thread identifier")
    message_id: str = Field(..., description="Message identifier")
    run_id: str = Field(..., description="Run identifier")
    assistant_id: str = Field(..., description="Assistant identifier")


class StatusEnum(PyEnum):
    deleted = "deleted"
    active = "active"               # Added this member
    queued = "queued"
    in_progress = "in_progress"
    pending_action = "action_required"
    completed = "completed"
    failed = "failed"
    cancelling = "cancelling"
    cancelled = "cancelled"
    pending = "pending"
    processing = "processing"
    expired = "expired"
    retrying = "retrying"


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
    participant_ids: Optional[List[str]] = Field(..., description="List of participant IDs"),
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


# Define the MessageRole enum
class MessageRole(str, Enum):
    PLATFORM = "platform"
    ASSISTANT = "assistant"
    USER = "user"
    SYSTEM = "system"
    TOOL = "tool"

# Add role validation to MessageCreate


class MessageCreate(BaseModel):
    content: str
    thread_id: str
    sender_id: Optional[str] = None
    assistant_id: str
    role: str  # String-based role instead of Enum
    tool_id: Optional[str] = None
    meta_data: Optional[Dict[str, Any]] = None
    is_last_chunk: bool = False

    @validator('role', pre=True)
    def validate_role(cls, v):
        valid_roles = {"platform", "assistant", "user", "system", "tool"}
        if isinstance(v, str):
            v = v.lower()
            if v in valid_roles:
                return v
        raise ValueError(f"Invalid role: {v}. Must be one of {list(valid_roles)}")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "Hello, this is a test message.",
                "thread_id": "example_thread_id",
                "assistant_id": "example_assistant_id",
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
    role: str  # String-based role
    run_id: Optional[str]
    tool_id: Optional[str] = None
    status: Optional[str]
    thread_id: str
    sender_id: Optional[str] = None  # ✅ Made Optional

    model_config = ConfigDict(from_attributes=True)


class MessageUpdate(BaseModel):
    content: Optional[str]
    meta_data: Optional[Dict[str, Any]]
    status: Optional[str]
    role: Optional[str]  # Now a plain string instead of Enum

    @validator('role', pre=True)
    def validate_role(cls, v):
        if v is None:
            return v
        valid_roles = {"platform", "assistant", "user", "system", "tool"}
        v = v.lower()
        if v in valid_roles:
            return v
        raise ValueError(f"Invalid role: {v}. Must be one of {list(valid_roles)}")

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
    name: Optional[str]  # Added name field
    function: Optional[ToolFunction]

    model_config = ConfigDict(from_attributes=True)


class ToolCreate(BaseModel):
    name: str  # Add the 'name' attribute
    type: str
    function: Optional[ToolFunction]

    @validator('function', pre=True, always=True)
    def parse_function(cls, v):
        if isinstance(v, ToolFunction):
            return v
        if isinstance(v, dict) and 'function' in v:
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
    name: Optional[str] = None  # Allow updating the name
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



class ActionStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    expired = "expired"
    cancelled = "cancelled"
    retrying = "retrying"

class ActionCreate(BaseModel):
    id: Optional[str] = None
    tool_name: Optional[str] = None
    run_id: str
    function_args: Optional[Dict[str, Any]] = {}
    expires_at: Optional[datetime] = None
    status: Optional[str] = "pending"  # Default to pending

    @validator('tool_name', pre=True, always=True)
    def validate_tool_fields(cls, v):
        if not v:
            raise ValueError('Tool name must be provided.')
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tool_name": "example_tool_name",
                "run_id": "example_run_id",
                "function_args": {"arg1": "value1", "arg2": "value2"},
                "expires_at": "2024-09-10T12:00:00Z",
                "status": "pending"
            }
        }
    )

# ------------------------
# Action Schemas (Corrected)
# ------------------------
class ActionRead(BaseModel):
    id: str
    run_id: Optional[str] = None  # No default
    tool_id: Optional[str] = None  # No default
    tool_name: Optional[str] = None  # No default
    triggered_at: Optional[str] = None  # Removed '123456' default
    expires_at: Optional[str] = None
    is_processed: Optional[bool] = None
    processed_at: Optional[str] = None
    status: Optional[str] = None  # Use ActionStatus enum for validation
    function_args: Optional[dict] = None
    result: Optional[dict] = None

    # Add configuration to strictly forbid extra fields
    model_config = ConfigDict(
        extra='forbid',
        validate_assignment=True
    )


class RunReadDetailed(BaseModel):
    id: str
    assistant_id: str
    cancelled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: int
    expires_at: Optional[int] = None
    failed_at: Optional[datetime] = None
    incomplete_details: Optional[Dict[str, Any]] = None
    instructions: str
    last_error: Optional[str] = None
    max_completion_tokens: Optional[int] = 1000
    max_prompt_tokens: Optional[int] = 500
    meta_data: Dict[str, Any]
    model: str
    object: str
    parallel_tool_calls: bool
    required_action: Optional[str] = None
    response_format: str
    started_at: Optional[int] = None
    status: str
    thread_id: str
    tool_choice: str
    tools: List[ToolRead]  # Nested tool details
    truncation_strategy: Dict[str, Any]
    usage: Optional[Any] = None
    temperature: float
    top_p: float
    tool_resources: Dict[str, Any]
    actions: List[ActionRead] = []  # Provide a default empty list

    model_config = ConfigDict(from_attributes=True)


class RunStatus(str, Enum):
    queued = "queued"
    in_progress = "in_progress"
    pending_action = "action_required"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    pending = "pending"
    processing = "processing"
    expired = "expired"
    retrying = "retrying"


class RunStatusUpdate(BaseModel):
    status: RunStatus


# Vector store
class VectorStoreStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    processing = "processing"
    error = "error"

class VectorStoreCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=128, description="Human-friendly store name")
    user_id: str = Field(..., min_length=3, description="Owner user ID (should be valid)")
    vector_size: int = Field(..., gt=0, description="Must be a positive integer")
    distance_metric: str = Field(..., description="Distance metric (COSINE, EUCLID, DOT)")
    config: Optional[Dict[str, Any]] = None

    @validator("distance_metric")
    def validate_distance_metric(cls, v):
        allowed_metrics = {"COSINE", "EUCLID", "DOT"}
        if v.upper() not in allowed_metrics:
            raise ValueError(f"Invalid distance metric: {v}. Must be one of {allowed_metrics}")
        return v


class VectorStoreRead(BaseModel):
    id: str
    name: str
    user_id: str
    collection_name: str
    vector_size: int
    distance_metric: str
    created_at: int
    updated_at: Optional[int] = None
    status: VectorStoreStatus
    config: Optional[Dict[str, Any]] = None
    file_count: int = Field(0, description="Number of files in store")

    model_config = ConfigDict(from_attributes=True)

class VectorStoreUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=128)
    status: Optional[VectorStoreStatus] = None
    config: Optional[Dict[str, Any]] = None

class VectorStoreFileCreate(BaseModel):
    file_name: str = Field(..., max_length=256)
    file_path: str = Field(..., max_length=1024)
    metadata: Optional[Dict[str, Any]] = None

class VectorStoreFileRead(BaseModel):
    id: str
    file_name: str
    file_path: str
    processed_at: Optional[int] = None
    status: entities_api.models.models.StatusEnum
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)

class VectorStoreFileUpdate(BaseModel):
    status: Optional[entities_api.models.models.StatusEnum] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class VectorStoreList(BaseModel):
    vector_stores: List[VectorStoreRead]

class VectorStoreFileList(BaseModel):
    files: List[VectorStoreFileRead]

class VectorStoreLinkAssistant(BaseModel):
    assistant_ids: List[str] = Field(..., min_items=1, description="List of assistant IDs to link")

class VectorStoreUnlinkAssistant(BaseModel):
    assistant_id: str = Field(..., description="Assistant ID to unlink")



class VectorStoreSearchResult(BaseModel):
    text: str
    metadata: Optional[dict] = None
    score: float
    vector_id: Optional[str] = ""  # Made optional with default empty string
    store_id: Optional[str] = ""   # Made optional with default empty string
    retrieved_at: int = int(time.time())



class ProcessOutput(BaseModel):
    store_name: str
    status: str
    chunks_processed: int


class AssistantCreate(BaseModel):
    id: Optional[str] = None
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
    user_id: Optional[str] = None
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
    vector_stores: Optional[List[VectorStoreRead]] = []
    model_config = ConfigDict(from_attributes=True)


class AssistantUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    model: Optional[str] = None
    instructions: Optional[str] = None
    tools: Optional[List[Tool]] = None
    meta_data: Optional[Dict[str, Any]] = None
    top_p: Optional[float] = None
    temperature: Optional[float] = None
    response_format: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ActionBase(BaseModel):
    id: str
    run_id: str
    triggered_at: datetime  # Use datetime for the timestamp
    expires_at: Optional[datetime] = None  # This now accepts a datetime
    is_processed: bool
    processed_at: Optional[datetime] = None
    status: str = "pending"
    function_args: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class ActionList(BaseModel):
    actions: List[ActionRead]


class ActionUpdate(BaseModel):
    status: ActionStatus  # Use the ActionStatus enum here
    result: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)



class SandboxBase(BaseModel):
    id: str
    user_id: str
    name: str
    created_at: datetime
    status: str
    config: Optional[Dict[str, Any]] = {}

    model_config = ConfigDict(from_attributes=True)


class SandboxCreate(BaseModel):
    user_id: str
    name: str
    config: Optional[Dict[str, Any]] = {}


class SandboxRead(SandboxBase):
    pass


class SandboxUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class CodeExecutionRequest(BaseModel):
    code: str
    language: str
    user_id: str


class CodeExecutionResponse(BaseModel):
    output: Optional[str] = None
    error: Optional[str] = None


# NEW: Added search explanation model
from pydantic import BaseModel
from typing import List, Dict, Optional

class SearchExplanation(BaseModel):
    """Provides transparency into search scoring and filtering"""
    base_score: float
    filters_passed: List[str]
    boosts_applied: Dict[str, float]
    final_score: float

class EnhancedVectorSearchResult(VectorStoreSearchResult):
    explanation: Optional[SearchExplanation] = None

