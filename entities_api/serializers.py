# api/v1/serializers.py
from pydantic import BaseModel, ConfigDict
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

class ThreadCreate(BaseModel):
    participant_ids: List[str]
    metadata: Optional[Dict[str, Any]] = {}

class ThreadRead(BaseModel):
    id: str
    created_at: int
    metadata: Dict[str, Any]
    object: str
    tool_resources: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)

class ThreadParticipant(UserBase):
    pass

class ThreadReadDetailed(ThreadRead):
    participants: List[UserBase]  # This is only for detailed views if needed


class Content(BaseModel):
    text: Dict[str, Any]
    type: str


class MessageCreate(BaseModel):
    content: List[Content]
    role: str
    thread_id: str
    msg_metadata: Optional[Dict[str, Any]] = {}


class MessageRead(BaseModel):
    id: str
    assistant_id: Optional[str]
    attachments: List[Any]
    completed_at: Optional[int]
    content: List[Content]
    created_at: int
    incomplete_at: Optional[int]
    incomplete_details: Optional[Dict[str, Any]]
    msg_metadata: Dict[str, Any]
    object: str
    role: str
    run_id: Optional[str]
    status: Optional[str]
    thread_id: str

    model_config = ConfigDict(from_attributes=True)
