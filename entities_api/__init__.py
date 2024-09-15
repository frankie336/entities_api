from entities_api.new_clients.client_assistant_client import ClientAssistantService
from entities_api.new_clients.client import OllamaClient

#from services.loggin_service import LoggingUtility

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
    'ClientAssistantService',
  'ClientMessageService',
  'RunService',
  'ThreadService',
  'UserService',
  'LoggingUtility'
]

_client = OllamaClient()

#generate = _client.generate
#chat = _client.chat
#embed = _client.embed
#embeddings = _client.embeddings
#pull = _client.pull
#push = _client.push
#create = _client.create
#delete = _client.delete
#list = _client.list
#copy = _client.copy
#show = _client.show
#ps = _client.ps
