from datetime import datetime
from typing import Dict, Any, Optional

from pydantic import BaseModel, ConfigDict


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
