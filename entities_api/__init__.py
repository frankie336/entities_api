from ollama._client import Client, AsyncClient
from entities_api.user_client import UserService
from entities_api.run_client import RunService
from entities_api._client import OllamaClient
from entities_api.thread_client import ThreadService
from entities_api.message_client import MessageService
from entities_api.assistant_client import AssistantService


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
  'Client',
  'AsyncClient',
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

_client = Client()

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
