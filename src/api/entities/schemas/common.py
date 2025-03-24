from enum import Enum
from enum import Enum as PyEnum
from typing import Dict, Any, Optional

from pydantic import BaseModel, Field, ConfigDict, validator

from entities.schemas.tools import Tool
from entities.schemas.tools import ToolFunction
from entities.schemas.vectors import VectorStoreStatus


class ProviderEnum(str, Enum):
    openai = "openai"
    deepseek = "deepseek"
    hyperbolic = "Hyperbolic"
    togetherai = "togetherai"
    local = "local"


class StatusEnum(PyEnum):
    deleted = "deleted"
    active = "active"  # Added this member
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


class ActionRead(BaseModel):
    id: str = Field(..., description="Unique identifier for the action", example="action_123456")
    run_id: Optional[str] = Field(None, description="Associated run ID for this action", example="run_123456")
    tool_id: Optional[str] = Field(None, description="Tool identifier associated with the action", example="tool_123456")
    tool_name: Optional[str] = Field(None, description="Name of the tool", example="code_interpreter")
    triggered_at: Optional[str] = Field(None, description="Timestamp when the action was triggered", example="2025-03-24T12:00:00Z")
    expires_at: Optional[str] = Field(None, description="Timestamp when the action expires", example="2025-03-24T12:05:00Z")
    is_processed: Optional[bool] = Field(None, description="Indicates if the action has been processed")
    processed_at: Optional[str] = Field(None, description="Timestamp when the action was processed", example="2025-03-24T12:01:00Z")
    status: Optional[str] = Field(None, description="Current status of the action", example="in_progress")
    function_args: Optional[dict] = Field(None, description="Arguments passed to the tool function", example={"param1": "value1"})
    result: Optional[dict] = Field(None, description="Result returned from executing the action", example={"output": "result data"})

    model_config = ConfigDict(
        extra='forbid',
        validate_assignment=True
    )


class VectorStoreRead(BaseModel):
    id: str = Field(..., description="Unique identifier for the vector store", example="vectorstore_123")
    name: str = Field(..., description="Name of the vector store", example="My Vector Store")
    user_id: str = Field(..., description="ID of the user that owns this vector store", example="user_123")
    collection_name: str = Field(..., description="Name of the collection in the vector store", example="my_collection")
    vector_size: int = Field(..., description="Size of the vectors stored", example=768)
    distance_metric: str = Field(..., description="Distance metric used (e.g., cosine, euclidean)", example="cosine")
    created_at: int = Field(..., description="Unix timestamp when the vector store was created", example=1640995200)
    updated_at: Optional[int] = Field(None, description="Unix timestamp when the vector store was last updated", example=1641081600)
    status: VectorStoreStatus = Field(..., description="Current status of the vector store")
    config: Optional[Dict[str, Any]] = Field(None, description="Additional configuration for the vector store")
    file_count: int = Field(0, description="Number of files in the vector store", example=10)

    model_config = ConfigDict(from_attributes=True)
