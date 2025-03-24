# src/api/entities/schemas/files.py
from fastapi import Form
from pydantic import BaseModel
from typing import Optional

class FileUploadRequest(BaseModel):
    """Schema for file upload request data."""
    purpose: str = Form(...)
    user_id: str = Form(...)

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