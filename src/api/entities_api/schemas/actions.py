from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic import validator


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

    @validator("tool_name", pre=True, always=True)
    def validate_tool_fields(cls, v):
        if not v:
            raise ValueError("Tool name must be provided.")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tool_name": "example_tool_name",
                "run_id": "example_run_id",
                "function_args": {"arg1": "value1", "arg2": "value2"},
                "expires_at": "2024-09-10T12:00:00Z",
                "status": "pending",
            }
        }
    )


class ActionRead(BaseModel):
    id: str = Field(..., description="Unique identifier for the action", example="action_123456")
    run_id: Optional[str] = Field(
        None, description="Associated run ID for this action", example="run_123456"
    )
    tool_id: Optional[str] = Field(
        None, description="Tool identifier associated with the action", example="tool_123456"
    )
    tool_name: Optional[str] = Field(
        None, description="Name of the tool", example="code_interpreter"
    )
    triggered_at: Optional[str] = Field(
        None, description="Timestamp when the action was triggered", example="2025-03-24T12:00:00Z"
    )
    expires_at: Optional[str] = Field(
        None, description="Timestamp when the action expires", example="2025-03-24T12:05:00Z"
    )
    is_processed: Optional[bool] = Field(
        None, description="Indicates if the action has been processed"
    )
    processed_at: Optional[str] = Field(
        None, description="Timestamp when the action was processed", example="2025-03-24T12:01:00Z"
    )
    status: Optional[str] = Field(
        None, description="Current status of the action", example="in_progress"
    )
    function_args: Optional[dict] = Field(
        None, description="Arguments passed to the tool function", example={"param1": "value1"}
    )
    result: Optional[dict] = Field(
        None,
        description="Result returned from executing the action",
        example={"output": "result data"},
    )

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ActionList(BaseModel):
    actions: List[ActionRead]


class ActionUpdate(BaseModel):
    status: ActionStatus  # Use the ActionStatus enum here
    result: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)
