from src.entities_api.clients.client import OllamaClient

from ollama._types import (
    GenerateResponse,
    ChatResponse,
    ProgressResponse,
    Message,
    Options,
    RequestError,
    ResponseError,
)

__all__ = [
    'GenerateResponse',
    'ChatResponse',
    'ProgressResponse',
    'Message',
    'Options',
    'RequestError',
    'ResponseError',
    'OllamaClient',
    'EntitiesEventHandler'


]

from src.entities_api.services.event_handler import EntitiesEventHandler

_client = OllamaClient()