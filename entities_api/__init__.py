from entities_api.clients.client_assistant_client import ClientAssistantService
from entities_api.clients.client import OllamaClient
from entities_api.clients.platform_tools.code_interpreter_handler import code_interpreter
from entities_api.services.event_handler import EntitiesEventHandler
from entities_api.inference.inference_factory import InferenceFactory
from entities_api.inference.local_inference import LocalInference
from entities_api.inference.cloud_inference import CloudInference
from entities_api.inference.llama_local import LlamaLocal


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
    'code_interpreter',
    'OllamaClient',
    'ClientAssistantService',
    'InferenceFactory',
    'LocalInference',
    'LlamaLocal',
    'CloudInference',
    'EntitiesEventHandler'
]

_client = OllamaClient()