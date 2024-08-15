from entities_api.new_clients.user_client import UserService
from entities_api.new_clients.assistant_client import AssistantService
from entities_api.new_clients.thread_client import ThreadService
from entities_api.new_clients.message_client import MessageService
from entities_api.new_clients.run_client import RunService
from entities_api.new_clients.runner import Runner


class OllamaClient:
    def __init__(self, base_url='http://localhost:9000/', api_key='your_api_key'):

        self.base_url = base_url
        self.api_key = api_key
        self.user_service = UserService(base_url, api_key)
        self.assistant_service = AssistantService(base_url, api_key)
        self.thread_service = ThreadService(base_url, api_key)
        self.message_service = MessageService(base_url, api_key)
        self.run_service = RunService(base_url, api_key)
        self.runner = Runner(base_url, api_key)

    def user_service(self):
        return self.user_service

    def assistant_service(self):
        return self.assistant_service

    def thread_service(self):
        return self.thread_service

    def message_service(self):

        return self.message_service

    def run_service(self):
        return self.run_service

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





if __name__ == "__main__":
    base_url = "http://localhost:8000/"
    api_key = "your_api_key"
    client = OllamaClient(base_url, api_key)

    # Create a user
    user1 = client.user_service.create_user(name='Test')
    userid = user1['id']

    # Create an assistant
    assistant = client.assistant_service.create_assistant(
        name='Mathy',
        description='My helpful maths tutor',
        model='llama3.1',
        instructions='Be as kind, intelligent, and helpful',
        tools=[{"type": "code_interpreter"}]
    )

    # Create thread
    thread = client.thead_service.create_thread(participant_ids=[userid], meta_data={"topic": "Test Thread"})
    thread_id = thread['id']

    # Create a message
    message_content = "Hello, can you help me with a math problem?"
    message = client.create_message(thread_id=thread_id, content=message_content, sender_id=userid, role='user')
    print(message)