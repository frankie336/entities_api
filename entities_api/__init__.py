from entities_api.clients.client_assistant_client import ClientAssistantService
from entities_api.clients.client import OllamaClient
from entities_api.clients.platform_tools.code_interpreter_handler import code_interpreter
from entities_api.clients.inference.inference_factory import InferenceFactory
from entities_api.clients.inference.base_inference import BaseInference
from entities_api.clients.inference.local_inference import LocalInference
from entities_api.clients.inference.cloud_inference import CloudInference

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
  'BaseInference',
  'LocalInference',
  'CloudInference'

]

_client = OllamaClient()

