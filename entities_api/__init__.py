
from new_clients.user_client import UserService
from new_clients.run_client import RunService
from new_clients.new_ollama_client import OllamaClient
from new_clients.thread_client import ThreadService
from new_clients.message_client import MessageService
from new_clients.assistant_client import AssistantService
from services.loggin_service import LoggingUtility

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
  'AssistantService',
  'MessageService',
  'RunService',
  'ThreadService',
  'UserService',
  'LoggingUtility'
]

_client = OllamaClient()

generate = _client.generate
chat = _client.chat
embed = _client.embed
embeddings = _client.embeddings
pull = _client.pull
push = _client.push
create = _client.create
delete = _client.delete
list = _client.list
copy = _client.copy
show = _client.show
ps = _client.ps
