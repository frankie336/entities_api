import time
from enum import Enum
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field, ConfigDict
from pydantic import validator

import entities.models.models
from entities.schemas.common import VectorStoreRead


class VectorStoreStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    processing = "processing"
    error = "error"

class VectorStoreCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=128, description="Human-friendly store name")
    user_id: str = Field(..., min_length=3, description="Owner user ID (should be valid)")
    vector_size: int = Field(..., gt=0, description="Must be a positive integer")
    distance_metric: str = Field(..., description="Distance metric (COSINE, EUCLID, DOT)")
    config: Optional[Dict[str, Any]] = None

    @validator("distance_metric")
    def validate_distance_metric(cls, v):
        allowed_metrics = {"COSINE", "EUCLID", "DOT"}
        if v.upper() not in allowed_metrics:
            raise ValueError(f"Invalid distance metric: {v}. Must be one of {allowed_metrics}")
        return v



class VectorStoreUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=128)
    status: Optional[VectorStoreStatus] = None
    config: Optional[Dict[str, Any]] = None

class VectorStoreFileCreate(BaseModel):
    file_name: str = Field(..., max_length=256)
    file_path: str = Field(..., max_length=1024)
    metadata: Optional[Dict[str, Any]] = None

class VectorStoreFileRead(BaseModel):
    id: str
    file_name: str
    file_path: str
    processed_at: Optional[int] = None
    status: entities.models.models.StatusEnum
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)

class VectorStoreFileUpdate(BaseModel):
    status: Optional[entities.models.models.StatusEnum] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class VectorStoreList(BaseModel):
    vector_stores: List[VectorStoreRead]

class VectorStoreFileList(BaseModel):
    files: List[VectorStoreFileRead]

class VectorStoreLinkAssistant(BaseModel):
    assistant_ids: List[str] = Field(..., min_items=1, description="List of assistant IDs to link")

class VectorStoreUnlinkAssistant(BaseModel):
    assistant_id: str = Field(..., description="Assistant ID to unlink")



class VectorStoreSearchResult(BaseModel):
    text: str
    metadata: Optional[dict] = None
    score: float
    vector_id: Optional[str] = ""  # Made optional with default empty string
    store_id: Optional[str] = ""   # Made optional with default empty string
    retrieved_at: int = int(time.time())


class SearchExplanation(BaseModel):
    """Provides transparency into search scoring and filtering"""
    base_score: float
    filters_passed: List[str]
    boosts_applied: Dict[str, float]
    final_score: float

class EnhancedVectorSearchResult(VectorStoreSearchResult):
    explanation: Optional[SearchExplanation] = None

