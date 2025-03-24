from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from entities.schemas.users import UserBase

class ThreadCreate(BaseModel):
    participant_ids: List[str] = Field(
        ...,
        description="List of participant IDs for the new thread."
    )
    meta_data: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional metadata for the thread."
    )

    model_config = ConfigDict(from_attributes=True)


class ThreadRead(BaseModel):
    id: str = Field(..., description="Unique identifier for the thread.")
    created_at: int = Field(..., description="Unix timestamp when the thread was created.")
    meta_data: Dict[str, Any] = Field(..., description="Metadata associated with the thread.")
    object: str = Field(..., description="Type of the object, typically 'thread'.", example="thread")
    tool_resources: Dict[str, Any] = Field(
        ...,
        description="Resources or tools associated with the thread."
    )

    model_config = ConfigDict(from_attributes=True)


class ThreadUpdate(BaseModel):
    participant_ids: Optional[List[str]] = Field(
        None,
        description="Updated list of participant IDs for the thread."
    )
    meta_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Updated metadata for the thread."
    )

    model_config = ConfigDict(from_attributes=True)


class ThreadParticipant(UserBase):
    """
    Represents a participant in a thread.
    Inherits common user fields from UserBase.
    """
    pass


class ThreadReadDetailed(ThreadRead):
    participants: List[UserBase] = Field(
        ...,
        description="List of user details for each participant in the thread."
    )

    model_config = ConfigDict(from_attributes=True)


class ThreadIds(BaseModel):
    thread_ids: List[str] = Field(
        ...,
        description="List of thread IDs."
    )

    model_config = ConfigDict(from_attributes=True)
