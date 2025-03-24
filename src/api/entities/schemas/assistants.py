from typing import List, Dict, Any, Optional

from pydantic import BaseModel

from entities.schemas.common import VectorStoreRead


# AssistantCreate model
class AssistantCreate(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    model: str
    instructions: str = ""
    tools: Optional[List[dict]] = None  # Use 'tools' for consistency
    meta_data: Optional[dict] = None
    top_p: float = 1.0
    temperature: float = 1.0
    response_format: str = "auto"

# AssistantRead model
class AssistantRead(BaseModel):
    id: str
    user_id: Optional[str] = None
    object: str
    created_at: int
    name: str
    description: Optional[str]
    model: str
    instructions: Optional[str]
    tools: Optional[List[dict]] = None  # Match with 'tools'
    meta_data: Optional[Dict[str, Any]] = None
    top_p: float
    temperature: float
    response_format: str
    vector_stores: Optional[List["VectorStoreRead"]] = []

# AssistantUpdate model
class AssistantUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    model: Optional[str] = None
    instructions: Optional[str] = None
    tools: Optional[List[Any]] = None  # Accepts dicts, auto-converted to Tool
    meta_data: Optional[Dict[str, Any]] = None
    top_p: Optional[float] = None
    temperature: Optional[float] = None
    response_format: Optional[str] = None
