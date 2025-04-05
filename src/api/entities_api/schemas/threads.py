from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field, ConfigDict

# Assuming UserBase is defined in entities_api.schemas.users; adjust import as needed
from entities_api.schemas.users import UserBase


class ThreadCreate(BaseModel):
    participant_ids: List[str] = Field(..., description="List of participant IDs")
    meta_data: Optional[Dict[str, Any]] = None


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
