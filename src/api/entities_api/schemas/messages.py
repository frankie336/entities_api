from enum import Enum
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, ConfigDict
from pydantic import validator


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

    @validator("role", pre=True)
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
                "role": "user",
            }
        }
    )


class ToolMessageCreate(BaseModel):
    content: str

    model_config = ConfigDict(
        json_schema_extra={"example": {"content": "This is the content of the tool message."}}
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

    @validator("role", pre=True)
    def validate_role(cls, v):
        if v is None:
            return v
        valid_roles = {"platform", "assistant", "user", "system", "tool"}
        v = v.lower()
        if v in valid_roles:
            return v
        raise ValueError(f"Invalid role: {v}. Must be one of {list(valid_roles)}")

    model_config = ConfigDict(from_attributes=True)
