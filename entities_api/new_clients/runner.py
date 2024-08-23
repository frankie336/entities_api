# new_clients/ex_new_ollama_client.py
import json
import os

from dotenv import load_dotenv

from entities_api.new_clients.assistant_client import AssistantService
from entities_api.new_clients.message_client import MessageService
from entities_api.new_clients.run_client import RunService
from entities_api.new_clients.thread_client import ThreadService
from entities_api.new_clients.user_client import UserService
from ollama import Client
from entities_api.services.loggin_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class Runner:
    def __init__(self, base_url=os.getenv('ASSISTANTS_BASE_URL'), api_key='your api key'):
        self.base_url = base_url or os.getenv('ASSISTANTS_BASE_URL')
        self.api_key = api_key or os.getenv('API_KEY')
        self.user_service = UserService(self.base_url, self.api_key)
        self.assistant_service = AssistantService(self.base_url, self.api_key)
        self.thread_service = ThreadService(self.base_url, self.api_key)
        self.message_service = MessageService(self.base_url, self.api_key)
        self.run_service = RunService(self.base_url, self.api_key)
        self.ollama_client = Client()
        logging_utility.info("Runner initialized with base_url: %s", self.base_url)

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
                self.run_service.update_run_activity(run_id)  # Update run activity for each chunk
                yield content

            logging_utility.info("Finished yielding all chunks")
            logging_utility.debug("Full response: %s", full_response)

            saved_message = self.message_service.save_assistant_message_chunk(thread_id, full_response,
                                                                              is_last_chunk=True)

            if saved_message:
                logging_utility.info("Assistant message saved successfully")
            else:
                logging_utility.warning("Failed to save assistant message")

            updated_run = self.run_service.complete_run(run_id)
            if updated_run:
                logging_utility.info("Run status updated to completed for run_id: %s", run_id)
            else:
                logging_utility.warning("Failed to update run status for run_id: %s", run_id)

        except Exception as e:
            logging_utility.error("Error in streamed_response_helper: %s", str(e), exc_info=True)
            self.run_service.fail_run(run_id, str(e))
            yield json.dumps({"error": "An error occurred while generating the response"})

        logging_utility.info("Exiting streamed_response_helper")

    def process_conversation(self, thread_id, run_id, assistant_id, model='llama3.1'):
        logging_utility.info("Processing conversation for thread_id: %s, run_id: %s, model: %s", thread_id, run_id, model)

        try:
            self.run_service.start_run(run_id)

            assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
            logging_utility.info("Retrieved assistant: id=%s, name=%s, model=%s",
                                 assistant.id, assistant.name, assistant.model)

            messages = self.message_service.get_formatted_messages(thread_id, system_message=assistant.instructions)
            logging_utility.debug("Formatted messages: %s", messages)

            for chunk in self.streamed_response_helper(messages, thread_id, run_id, model):
                yield chunk

        except Exception as e:
            logging_utility.error("Error in process_conversation: %s", str(e), exc_info=True)
            self.run_service.fail_run(run_id, str(e))
            yield json.dumps({"error": "An error occurred while processing the conversation"})

        logging_utility.info("Conversation processed successfully")


