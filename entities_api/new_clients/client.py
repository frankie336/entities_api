from entities_api.new_clients.actions_client import ClientActionService
from entities_api.new_clients.assistant_client import AssistantService
from entities_api.new_clients.message_client import MessageService
from entities_api.new_clients.run_client import RunService
from entities_api.new_clients.runner import Runner
from entities_api.new_clients.thread_client import ThreadService
from entities_api.new_clients.tool_client import ClientToolService
from entities_api.new_clients.user_client import UserService


class OllamaClient:
    def __init__(self, base_url='http://localhost:9000/', api_key='your_api_key', available_functions=None):

        self.base_url = base_url
        self.api_key = api_key
        self.user_service = UserService(base_url, api_key)
        self.assistant_service = AssistantService(base_url, api_key)
        self.tool_service = ClientToolService(base_url, api_key)
        self.thread_service = ThreadService(base_url, api_key)
        self.message_service = MessageService(base_url, api_key)
        self.run_service = RunService(base_url, api_key)
        self.available_functions = available_functions
        self.runner = Runner(base_url, api_key, available_functions=self.available_functions)
        self.actions_service = ClientActionService(base_url, api_key)

    def user_service(self):
        return self.user_service

    def assistant_service(self):
        return self.assistant_service

    def tool_service(self):
        return self.tool_service

    def thread_service(self):
        return self.thread_service

    def message_service(self):

        return self.message_service

    def run_service(self):
        return self.run_service

    def action_service(self):
        return self.actions_service


    def create_message(self, thread_id, content, role):
        data = [
            {
                "type": "text",
                "text": {
                    "value": content,
                    "annotations": []
                }
            }
        ]

        message = self.message_service.create_message(thread_id=thread_id, content=data, role=role)
        return message

    def runner(self):
        return self.runner





