from entities_api.new_clients.client_assistant_client import ClientAssistantService
from entities_api.new_clients.client import OllamaClient
from entities_api.new_clients.platform_tools.code_interpreter_handler import code_interpreter



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
  'generate',
  'chat',
  'embed',
  'embeddings',
  'pull',
  'push',
  'create',
  'delete',
  'list',
  'copy',
  'show',
  'ps',
  'OllamaClient',
    'ClientAssistantService',
  'ClientMessageService',
  'RunService',
  'ThreadService',
  'UserService',
  'LoggingUtility'
]

_client = OllamaClient()

