# File: src/api/entities_api/routers/streaming.py

from enum import Enum
from typing import AsyncGenerator, Optional

import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Import your inference arbiter and selector
from entities_api.inference.inference_arbiter import InferenceArbiter
from entities_api.inference.inference_provider_selector import InferenceProviderSelector

router = APIRouter()


class ProviderEnum(str, Enum):
    openai = "openai"
    deepseek = "deepseek"
    hyperbolic = "hyperbolic"
    togetherai = "togetherai"
    local = "local"


class StreamRequest(BaseModel):
    provider: ProviderEnum = Field(..., description="The inference provider")
    model: str = Field(..., description="The model to use for inference")
    api_key: Optional[str] = Field(None, description="Optional API key for third-party providers")
    thread_id: str = Field(..., description="Thread identifier")
    message_id: str = Field(..., description="Message identifier")
    run_id: str = Field(..., description="Run identifier")
    assistant_id: str = Field(..., description="Assistant identifier")


@router.post(
    "/stream",
    summary="Stream real-time AI assistant response",
    response_description="A stream of JSON-formatted response chunks"
)
async def stream_response(request: StreamRequest):
    """
    Streams the AI assistant's response in real time. Uses the InferenceProviderSelector
    to pick the proper provider instance, then delegates to its process_conversation method.
    """
    try:
        return StreamingResponse(
            conversation_generator(request),
            media_type="text/event-stream"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")


async def conversation_generator(req: StreamRequest) -> AsyncGenerator[str, None]:
    """
    Selects the appropriate inference provider and streams its conversation output.
    """
    # Instantiate the arbiter and selector
    arbiter = InferenceArbiter()
    selector = InferenceProviderSelector(arbiter)

    # Select the proper provider instance based on the request parameters
    try:
        provider_instance = selector.select_provider(provider=req.provider.value, model=req.model)
    except ValueError as ve:
        yield f"data: {json.dumps({'type': 'error', 'content': str(ve)})}\n\n"
        return

    # Wrap the (synchronous) process_conversation call for async execution.
    try:
        async for chunk in async_process_conversation(provider_instance, req):
            yield f"data: {json.dumps(chunk)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"


async def async_process_conversation(provider_instance, req: StreamRequest) -> AsyncGenerator[dict, None]:
    """
    Wraps the provider's process_conversation method—which yields response chunks—
    to run in an asynchronous context. Adjust this if your provider is natively async.
    """
    loop = asyncio.get_running_loop()

    # Define a synchronous function to run the conversation generator
    def run_conversation():
        # process_conversation is expected to yield chunks in a for-loop
        return list(provider_instance.process_conversation(
            thread_id=req.thread_id,
            message_id=req.message_id,
            run_id=req.run_id,
            assistant_id=req.assistant_id,
            model=req.model,
            stream_reasoning=False
        ))

    # Offload the synchronous generator to an executor
    chunks = await loop.run_in_executor(None, run_conversation)
    for chunk in chunks:
        yield chunk
