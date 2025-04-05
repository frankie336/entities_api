from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, ConfigDict

from entities_api.schemas.actions import ActionRead
from entities_api.schemas.tools import Tool
from entities_api.schemas.tools import ToolRead


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
