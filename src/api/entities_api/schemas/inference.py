from typing import Optional

from entities_common import ValidationInterface
from pydantic import BaseModel, Field

validator = ValidationInterface()


class ProcessOutput(BaseModel):
    store_name: str
    status: str
    chunks_processed: int


class StreamRequest(BaseModel):
    provider: validator.ProviderEnum = Field(..., description="The inference provider")
    model: str = Field(..., description="The model to use for inference")
    api_key: Optional[str] = Field(None, description="Optional API key for third-party providers")
    thread_id: str = Field(..., description="Thread identifier")
    message_id: str = Field(..., description="Message identifier")
    run_id: str = Field(..., description="Run identifier")
    assistant_id: str = Field(..., description="Assistant identifier")
