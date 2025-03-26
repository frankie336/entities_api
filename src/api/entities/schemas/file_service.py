# src/api/entities_api/schemas/file_service.py
from typing import Optional

from pydantic import BaseModel


class FileUploadRequest(BaseModel):
    """Schema for file upload request data"""
    purpose: str
    user_id: str


class FileResponse(BaseModel):
    """Schema for file response data."""
    id: str
    object: str = "file"
    bytes: int
    created_at: int
    filename: str
    purpose: str
    status: str = "uploaded"
    expires_at: Optional[int] = None

    class Config:
        from_attributes = True
