from enum import Enum
from enum import Enum as PyEnum
from typing import Dict, Any, Optional

from pydantic import BaseModel, Field, ConfigDict
from pydantic import validator

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
