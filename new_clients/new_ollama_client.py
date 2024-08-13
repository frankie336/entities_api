# new_clients/new_ollama_client.py
import json
import os
import time

from dotenv import load_dotenv

from new_clients.assistant_client import AssistantService
from new_clients.message_client import MessageService
from new_clients.run_client import RunService
from new_clients.thread_client import ThreadService
from new_clients.user_client import UserService
from ollama import Client
from services.loggin_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class OllamaClient:
    def __init__(self, base_url=os.getenv('ASSISTANTS_BASE_URL'), api_key='your api key'):
        self.base_url = base_url or os.getenv('ASSISTANTS_BASE_URL')
        self.api_key = api_key or os.getenv('API_KEY')
        self.user_service = UserService(self.base_url, self.api_key)
        self.assistant_service = AssistantService(self.base_url, self.api_key)
        self.thread_service = ThreadService(self.base_url, self.api_key)
        self.message_service = MessageService(self.base_url, self.api_key)
        self.run_service = RunService(self.base_url, self.api_key)
        self.ollama_client = Client()
        logging_utility.info("OllamaClient initialized with base_url: %s", self.base_url)

    def create_thread(self):
        logging_utility.info("Creating new thread")
        thread = self.thread_service.create_thread(participant_ids=None, meta_data=None)
        logging_utility.info("Thread created with ID: %s", thread['id'])
        return thread

    def create_message(self, thread_id, content, role, sender_id):
        logging_utility.info("Creating message for thread_id: %s, role: %s", thread_id, role)
        message = self.message_service.create_message(thread_id=thread_id, content=content, role=role,
                                                      sender_id=sender_id)
        logging_utility.info("Message created with ID: %s", message['id'])
        return message

    def create_run(self, thread_id, assistant_id, instructions):
        logging_utility.info("Creating run for thread_id: %s, assistant_id: %s", thread_id, assistant_id)
        run = self.run_service.create_run(assistant_id=assistant_id,
                                          thread_id=thread_id,
                                          instructions=instructions)
        logging_utility.info("Run created with ID: %s", run['id'])
        return run

    def streamed_response_helper(self, messages, thread_id, run_id, model='llama3.1'):
        logging_utility.info("Starting streamed response for thread_id: %s, run_id: %s, model: %s", thread_id, run_id, model)
        try:
            response = self.ollama_client.chat(
                model=model,
                messages=messages,
                options={'num_ctx': 4096},
                stream=True
            )

            logging_utility.info("Response received from Ollama client")
            full_response = ""
            for chunk in response:
                content = chunk['message']['content']
                full_response += content
                logging_utility.debug("Received chunk: %s", content)
                yield content

            logging_utility.info("Finished yielding all chunks")
            logging_utility.debug("Full response: %s", full_response)

            saved_message = self.message_service.save_assistant_message_chunk(thread_id, full_response,
                                                                              is_last_chunk=True)

            if saved_message:
                logging_utility.info("Assistant message saved successfully")
            else:
                logging_utility.warning("Failed to save assistant message")

            updated_run = self.run_service.update_run_status(run_id, "completed")
            if updated_run:
                logging_utility.info("Run status updated to completed for run_id: %s", run_id)
            else:
                logging_utility.warning("Failed to update run status for run_id: %s", run_id)

        except Exception as e:
            logging_utility.error("Error in streamed_response_helper: %s", str(e), exc_info=True)
            yield json.dumps({"error": "An error occurred while generating the response"})

        logging_utility.info("Exiting streamed_response_helper")

    def process_conversation(self, thread_id, run_id, assistant_id, model='llama3.1'):
        logging_utility.info("Processing conversation for thread_id: %s, run_id: %s, model: %s", thread_id, run_id,
                             model)

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)

        logging_utility.info("Retrieved assistant: id=%s, name=%s, model=%s",
                             assistant.id, assistant.name, assistant.model)

        messages = self.message_service.get_formatted_messages(thread_id, system_message=assistant.instructions)
        logging_utility.debug("Formatted messages: %s", messages)
        return self.streamed_response_helper(messages, thread_id, run_id, model)


if __name__ == "__main__":
    logging_utility.info("Starting OllamaClient main script")
    client = OllamaClient()

    user1 = client.user_service.create_user(name='Test')
    userid = user1.id
    logging_utility.info("Created user with ID: %s", userid)

    assistant = client.assistant_service.create_assistant(
        name='Mathy',
        description='My helpful maths tutor',
        model='llama3.1',
        instructions='Be as kind, intelligent, and helpful',
        tools=[{"type": "code_interpreter"}]
    )

    # assistant_id = assistant['id']
    assistant_id = "asst_FuirCRmKlUvz4uNVVottMv"

    logging_utility.info("Created assistant with ID: %s", assistant_id)

    #assistant = client.assistant_service.retrieve_assistant(assistant_id=assistant_id)
    #logging_utility.info("Retrieved assistant: %s", assistant)

    thread = client.thread_service.create_thread(participant_ids=[userid], meta_data={"topic": "Test Thread"})
    logging_utility.info("Created thread with ID: %s", thread.id)

    user_message = "Hello, can you help me with a math problem?"
    client.message_service.create_message(thread_id=thread.id,
                                          content=user_message,
                                          role='user',
                                          sender_id=userid)
    logging_utility.info("Created user message in thread: %s", thread.id)

    run = client.run_service.create_run(thread_id=thread.id,
                                        assistant_id=userid)
    run_id = run['id']
    logging_utility.info("Created run with ID: %s", run_id)

    logging_utility.info("Processing conversation")
    for chunk in client.process_conversation(thread_id=thread.id, run_id=run_id, assistant_id=assistant_id):
        logging_utility.debug("Received chunk: %s", chunk)

    logging_utility.info("Conversation processed successfully")