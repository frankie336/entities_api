import json
import time

from dotenv import load_dotenv
from openai import OpenAI

from entities_api.clients.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.client_tool_client import ClientToolService

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()

class DeepSeekV3Cloud(BaseInference):
    def setup_services(self):
        """
        Initialize the DeepSeek client and other services.
        """
        self.deepseek_client = OpenAI(
            api_key="sk-f7c38a5f36e44b3e849d13b7e40f7157",
            base_url="https://api.deepseek.com"
        )
        logging_utility.info("DeepSeekR1Cloud specific setup completed.")

    def normalize_roles(self, conversation_history):
        """
        Normalize roles to ensure consistency with DeepSeek's API.
        """
        normalized_history = []
        for message in conversation_history:
            role = message.get('role', '').strip().lower()
            if role not in ['user', 'assistant', 'system']:
                role = 'user'
            normalized_history.append({
                "role": role,
                "content": message.get('content', '').strip()
            })
        return normalized_history

    def look_for_tool_call_trigger(self, message_id, model, assistant_id):
        """
        Check if the incoming message triggers a tool call.
        """
        message_service = ClientMessageService()
        message_data = message_service.retrieve_message(message_id=message_id)
        message = message_data.content

        # Handling tools
        tool_service = ClientToolService()
        tools_data = tool_service.list_tools(assistant_id=assistant_id)
        tools = tool_service.restructure_tools(tools_data)

        response = self.deepseek_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message}],
            stream=False,
            temperature=0.3,
            tools=tools
        )

        # Return the message object from the response
        return response.choices[0].message

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model='deepseek-reasoner', stream_reasoning=True):
        """
        Process conversation with dual streaming (content + reasoning).
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

        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )

        conversation_history = self.normalize_roles(conversation_history)
        deepseek_messages = [{"role": msg['role'], "content": msg['content']}
                             for msg in conversation_history]

        # Check for tool call trigger
        tool_call = self.look_for_tool_call_trigger(message_id, model, assistant_id)

        # If a tool call is triggered, save the triggering message
        if tool_call and hasattr(tool_call, 'tool_calls') and tool_call.tool_calls:
            tool_call_check = tool_call.tool_calls[0]
            logging_utility.info("Tool call triggered: %s", tool_call_check)

            # Save the tool-triggering message to the database
            message_service = ClientMessageService()
            message_data = message_service.retrieve_message(message_id=message_id)
            message = message_data.content


            self.message_service.save_assistant_message_chunk(thread_id=thread_id, content=message,
                                                              role='assistant',
                                                              is_last_chunk=True)

            logging_utility.info("Saving user message to thread: %s", thread_id)

            # Do not yield any response, just return
            return

        # If no tool call is triggered, proceed with the rest of the conversation
        tool_service = ClientToolService()
        tools_data = tool_service.list_tools(assistant_id=assistant_id)
        tools = tool_service.restructure_tools(tools_data)

        try:
            stream_response = self.deepseek_client.chat.completions.create(
                model=model,
                messages=deepseek_messages,
                stream=True,
                temperature=0.3,
                tools=tools
            )

            assistant_reply = ""
            reasoning_content = ""

            for chunk in stream_response:
                # Log the raw chunk for debugging
                logging_utility.debug("Raw chunk received: %s", chunk)

                # Extract reasoning content
                reasoning_chunk = getattr(chunk.choices[0].delta, 'reasoning_content', '')
                if reasoning_chunk:
                    reasoning_content += reasoning_chunk
                    logging_utility.debug("Thinking step: %s", reasoning_chunk)
                    yield json.dumps({
                        'type': 'reasoning',
                        'content': reasoning_chunk
                    })

                # Extract main content
                content_chunk = getattr(chunk.choices[0].delta, 'content', '')
                if content_chunk:
                    assistant_reply += content_chunk
                    logging_utility.debug("Content chunk: %s", content_chunk)
                    yield json.dumps({
                        'type': 'content',
                        'content': content_chunk
                    })

                # Prevent chunk merging
                time.sleep(0.01)

        except Exception as e:
            error_msg = "[ERROR] DeepSeek API streaming error"
            logging_utility.error(f"{error_msg}: {str(e)}", exc_info=True)
            yield json.dumps({
                'type': 'error',
                'content': error_msg
            })
            return

        # Save final message state
        if assistant_reply:

            self.message_service.save_assistant_message_chunk(thread_id=thread_id, content=assistant_reply,
                                                              role='assistant',
                                                              is_last_chunk= True)


            logging_utility.info("Assistant response stored successfully.")

        if reasoning_content:
            logging_utility.info("Final reasoning content: %s", reasoning_content)