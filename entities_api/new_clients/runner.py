import os
import uuid
from dotenv import load_dotenv
from groq import Groq

# Importing services
from entities_api.new_clients.client_actions_client import ClientActionService
from entities_api.new_clients.client_assistant_client import ClientAssistantService
from entities_api.new_clients.client_message_client import ClientMessageService
from entities_api.new_clients.client_run_client import RunService
from entities_api.new_clients.client_thread_client import ThreadService
from entities_api.new_clients.client_tool_client import ClientToolService
from entities_api.new_clients.client_user_client import UserService
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class Runner:
    def __init__(self, base_url=os.getenv('ASSISTANTS_BASE_URL'), api_key=None, available_functions=None):
        self.base_url = base_url or os.getenv('ASSISTANTS_BASE_URL')
        self.api_key = api_key or os.getenv('API_KEY')
        self.user_service = UserService(self.base_url, self.api_key)
        self.assistant_service = ClientAssistantService(self.base_url, self.api_key)
        self.thread_service = ThreadService(self.base_url, self.api_key)
        self.message_service = ClientMessageService(self.base_url, self.api_key)
        self.run_service = RunService(self.base_url, self.api_key)
        self.tool_service = ClientToolService(self.base_url, self.api_key)
        self.action_service = ClientActionService(self.base_url, self.api_key)
        self.available_functions = available_functions or {}

        # Initialize Groq API client
        self.groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))

        logging_utility.info("Runner initialized with base_url: %s", self.base_url)

    def truncate_conversation_history(self, conversation_history, max_exchanges=10):
        """
        Truncates the conversation history to the specified number of exchanges while retaining the system message.

        Args:
            conversation_history (list): The list of previous messages in the conversation.
            max_exchanges (int): The maximum number of user-assistant exchanges to retain.

        Returns:
            list: The truncated conversation history with the system prompt retained.
        """
        # Separate the system message if present
        system_messages = [msg for msg in conversation_history if msg['role'] == 'System']
        non_system_messages = [msg for msg in conversation_history if msg['role'] != 'System']

        # Each exchange consists of two messages: User and Assistant
        max_messages = max_exchanges * 2

        # Truncate only the non-system messages to the max allowed
        if len(non_system_messages) > max_messages:
            non_system_messages = non_system_messages[-max_messages:]

        # Combine the retained system message(s) with the truncated conversation history
        return system_messages + non_system_messages


    def normalize_roles(self, conversation_history):
        normalized_history = []
        for message in conversation_history:
            role = message.get('role', '').strip().capitalize()
            if role not in ['User', 'Assistant', 'System']:
                role = 'User'
            normalized_history.append({
                "role": role,
                "content": message.get('content', '').strip()
            })
        return normalized_history

    def process_conversation(self, thread_id, message_id, run_id, assistant_id, user_message):
        """
        Generates a response using Groq's chat completion API and streams the response back.

        Args:
            thread_id (str): Identifier for the conversation thread.
            message_id (str): Identifier for the specific message.
            run_id (str): Identifier for the run instance.
            assistant_id (str): Identifier for the assistant.
            user_message (str): The latest message from the user.

        Yields:
            str: Chunks of the assistant's response.
        """

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info(
            "Retrieved assistant: id=%s, name=%s, model=%s",
            assistant.id, assistant.name, assistant.model
        )

        system_prompt = assistant.instructions

        # Define the system prompt
        #system_prompt = "You are a helpful assistant that provides concise and informative answers."

        # Retrieve the formatted message history, including the system prompt as part of the instructions
        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        logging_utility.debug("Original formatted messages with system prompt included: %s", conversation_history)

        # Normalize roles to ensure consistency
        conversation_history = self.normalize_roles(conversation_history)
        logging_utility.debug("Normalized conversation history: %s", conversation_history)


        # Include system messages along with user and assistant messages
        conversation_history = [msg for msg in conversation_history if
                                msg['role'].lower() in ['user', 'assistant', 'system']]
        logging_utility.debug("Filtered conversation history (User, Assistant, and System): %s", conversation_history)

        # Truncate the conversation history to maintain the last 10 exchanges
        conversation_history = self.truncate_conversation_history(conversation_history, max_exchanges=10)
        logging_utility.debug("Truncated conversation history: %s", conversation_history)

        # Check if the last message is the same as the new user message to prevent duplication
        if not (conversation_history and
                conversation_history[-1]['role'] == 'User' and
                conversation_history[-1]['content'] == user_message):
            # Append the new user message to the conversation history
            conversation_history.append({"role": "User", "content": user_message})
            logging_utility.debug("Appended new user message to conversation history.")
        else:
            logging_utility.debug("New user message already exists in conversation history. Skipping append.")

        # Directly use the conversation history as messages for Groq API
        groq_messages = [{"role": msg['role'].lower(), "content": msg['content']} for msg in conversation_history]
        logging_utility.debug(f"Messages for Groq API:\n{groq_messages}")

        try:
            # Call the Groq API for generating chat completion with streaming enabled
            logging_utility.info("Started generating response stream using Groq API.")
            stream_response = self.groq_client.chat.completions.create(
                messages=groq_messages,
                model="llama-3.1-70b-versatile",
                stream=True,  # Enable streaming
                temperature=0.1,
                max_tokens=8000,
                top_p=1,
            )

            assistant_reply = ""

            # Process each chunk from the streaming response
            for chunk in stream_response:
                content = chunk.choices[0].delta.content
                if content:
                    assistant_reply += content
                    logging_utility.debug(f"Streaming chunk received: {content}")
                    yield content  # Yield each chunk as it is received

        except Exception as e:
            error_message = "[ERROR] An error occurred during streaming with Groq API."
            logging_utility.error(f"Error during Groq API streaming: {str(e)}", exc_info=True)
            yield error_message
            return  # Exit the generator after yielding the error

        # Save the assistant's complete response to the message service
        if assistant_reply:
            self.message_service.save_assistant_message_chunk(thread_id, assistant_reply, is_last_chunk=True)
            logging_utility.info("Assistant response stored successfully.")
