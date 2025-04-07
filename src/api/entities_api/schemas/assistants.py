from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from entities_api.schemas.vectors import VectorStoreRead


class AssistantCreate(BaseModel):
    id: Optional[str] = Field(
        None, description="Unique identifier for the assistant. Optional on creation."
    )
    name: str = Field(..., description="Name of the assistant", example="ChatGPT Assistant")
    description: str = Field(
        "",
        description="A brief description of the assistant",
        example="An assistant for handling tasks",
    )
    model: str = Field(..., description="Model used by the assistant", example="gpt-4")
    instructions: str = Field(
        "",
        description="Special instructions or guidelines for the assistant",
        example="Be friendly and concise",
    )
    tools: Optional[List[dict]] = Field(
        None, description="A list of tools available to the assistant, each defined as a dictionary"
    )
    meta_data: Optional[dict] = Field(None, description="Additional metadata for the assistant")
    top_p: float = Field(1.0, description="Top-p sampling parameter for text generation")
    temperature: float = Field(1.0, description="Temperature parameter for text generation")
    response_format: str = Field(
        "auto", description="Format of the assistant's response", example="auto"
    )


class AssistantRead(BaseModel):
    id: str = Field(..., description="Unique identifier for the assistant")
    user_id: Optional[str] = Field(
        None, description="Identifier for the user associated with the assistant"
    )
    object: str = Field(..., description="Object type", example="assistant")
    created_at: int = Field(..., description="Timestamp when the assistant was created")
    name: str = Field(..., description="Name of the assistant")
    description: Optional[str] = Field(None, description="Description of the assistant")
    model: str = Field(..., description="Model used by the assistant")
    instructions: Optional[str] = Field(None, description="Instructions provided to the assistant")
    tools: Optional[List[dict]] = Field(
        None, description="List of tool definitions associated with the assistant"
    )
    meta_data: Optional[Dict[str, Any]] = Field(
        None, description="Additional metadata for the assistant"
    )
    top_p: float = Field(..., description="Top-p sampling parameter")
    temperature: float = Field(..., description="Temperature parameter")
    response_format: str = Field(..., description="Response format")
    vector_stores: Optional[List[VectorStoreRead]] = Field(
        default_factory=list, description="List of associated vector stores"
    )


class AssistantUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Updated name for the assistant")
    description: Optional[str] = Field(None, description="Updated description for the assistant")
    model: Optional[str] = Field(None, description="Updated model name")
    instructions: Optional[str] = Field(None, description="Updated instructions for the assistant")
    tools: Optional[List[Any]] = Field(None, description="Updated list of tools for the assistant")
    meta_data: Optional[Dict[str, Any]] = Field(
        None, description="Updated metadata for the assistant"
    )
    top_p: Optional[float] = Field(None, description="Updated top-p parameter")
    temperature: Optional[float] = Field(None, description="Updated temperature parameter")
    response_format: Optional[str] = Field(None, description="Updated response format")
