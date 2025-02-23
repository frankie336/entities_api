import os
from dotenv import load_dotenv
from groq import Groq
from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class CloudInference(BaseInference):
    def setup_services(self):
        self.groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))
        logging_utility.info("CloudInference specific setup completed.")

    def truncate_conversation_history(self, conversation_history, max_exchanges=10):
        max_messages = max_exchanges * 2
        if len(conversation_history) > max_messages:
            conversation_history = conversation_history[-max_messages:]
        return conversation_history

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

    def process_conversation(self, thread_id, message_id, run_id, assistant_id, user_message, model='llama-3.1-70b-versatile'):
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

        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id, run_id, assistant_id
        )

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info(
            "Retrieved assistant: id=%s, name=%s, model=%s",
            assistant.id, assistant.name, assistant.model
        )

        # Retrieve the formatted message history, including the system prompt as part of the instructions
        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        logging_utility.debug("Original formatted messages with system prompt included: %s", conversation_history)

        # Normalize roles to ensure consistency
        conversation_history = self.normalize_roles(conversation_history)
        logging_utility.debug("Normalized conversation history: %s", conversation_history)

        # Exclude system messages since the system prompt has already been included correctly
        conversation_history = [msg for msg in conversation_history if msg['role'] in ['User', 'Assistant']]
        logging_utility.debug("Filtered conversation history (User and Assistant only): %s", conversation_history)

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
        # Include the system message as the first message
        groq_messages = [{"role": "system", "content": assistant.instructions}] + [
            {"role": msg['role'].lower(), "content": msg['content']} for msg in conversation_history]
        logging_utility.debug(f"Messages for Groq API:\n{groq_messages}")
        try:
            # Call the Groq API for generating chat completion with streaming enabled
            logging_utility.info("Started generating response stream using Groq API.")
            stream_response = self.groq_client.chat.completions.create(
                messages=groq_messages,
                model=model,
                stream=True,  # Enable streaming
                temperature=0.1,
                max_tokens=8000,
                top_p=1,
            )

            assistant_reply = ""
            # Process each chunk from the streaming response
            for chunk in stream_response:
                content = chunk.choices[0].delta.content

                # Check if the run has been cancelled during response generation
                # This block of code is newly added to handle cancellation logic
                current_run_status = self.run_service.retrieve_run(run_id=run_id).status
                if current_run_status in ["cancelling", "cancelled"]:
                    logging_utility.info(f"Run {run_id} is being cancelled or already cancelled, stopping response generation.")
                    break  # Stop processing if the run has been cancelled

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
