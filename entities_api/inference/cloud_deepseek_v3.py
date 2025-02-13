import json
import time
from dotenv import load_dotenv
from openai import OpenAI

from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_tool_client import ClientToolService
from entities_api.clients.client_run_client import ClientRunService

load_dotenv()
logging_utility = LoggingUtility()

class DeepSeekV3Cloud(BaseInference):
    def setup_services(self):
        """
        Initialize the DeepSeek client and other services.
        """
        self.deepseek_client = OpenAI(
            api_key="sk-33b3dbc54dd7408793117d410788acbf",
            base_url="https://api.deepseek.com"
        )
        logging_utility.info("DeepSeekV3Cloud specific setup completed.")

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

        return response.choices[0].message

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model='deepseek-reasoner', stream_reasoning=True):
        """
        Process conversation with dual streaming (content + reasoning). If a tool call trigger
        is detected, update run status to 'action_required', then wait for the status to change,
        and reprocess the original prompt.
        """
        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id, run_id, assistant_id
        )

        # Retrieve the assistant (and its instructions) via some service.
        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info("Retrieved assistant: id=%s, name=%s, model=%s",
                             assistant.id, assistant.name, assistant.model)

        # Retrieve conversation history and normalize roles.
        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        conversation_history = self.normalize_roles(conversation_history)
        deepseek_messages = [{"role": msg['role'], "content": msg['content']} for msg in conversation_history]

        # Look for a tool call trigger in the initial assistant response.
        tool_call = self.look_for_tool_call_trigger(message_id, model, assistant_id)
        if tool_call and hasattr(tool_call, 'tool_calls') and tool_call.tool_calls:
            tool_call_check = tool_call.tool_calls[0]
            logging_utility.info("Tool call triggered: %s", tool_call_check)

            # Save the user message that triggered the tool.
            message_service = ClientMessageService()
            message_data = message_service.retrieve_message(message_id=message_id)
            message = message_data.content
            self.message_service.save_assistant_message_chunk(
                thread_id=thread_id,
                content=message,
                role="user",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True
            )
            logging_utility.info("Saved triggering message to thread: %s", thread_id)

            # Save the tool invocation for state management.
            action_service = ClientActionService()
            data_dict = json.loads(tool_call_check.function.arguments)
            action_service.create_action(
                tool_name=tool_call_check.function.name,
                run_id=run_id,
                function_args=data_dict
            )

            # Update run status to 'action_required'
            run_service = ClientRunService()
            run_service.update_run_status(run_id=run_id, new_status='action_required')
            logging_utility.info(f"Run {run_id} status updated to action_required")

            # Now wait for the run's status to change from 'action_required'.
            while True:
                run = self.run_service.retrieve_run(run_id)
                if run.status != "action_required":
                    break
                time.sleep(1)
            logging_utility.info("Action status transition complete. Reprocessing conversation.")

            # Continue processing the conversation transparently.
            # (Rebuild the conversation history if needed; here we re-use deepseek_messages.)
        else:
            logging_utility.info("No tool call triggered; proceeding with conversation.")

        # Retrieve tools again (in case they changed)
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
                logging_utility.debug("Raw chunk received: %s", chunk)
                reasoning_chunk = getattr(chunk.choices[0].delta, 'reasoning_content', '')
                if reasoning_chunk:
                    reasoning_content += reasoning_chunk
                    yield json.dumps({
                        'type': 'reasoning',
                        'content': reasoning_chunk
                    })
                content_chunk = getattr(chunk.choices[0].delta, 'content', '')
                if content_chunk:
                    assistant_reply += content_chunk
                    yield json.dumps({
                        'type': 'content',
                        'content': content_chunk
                    })
                time.sleep(0.01)
        except Exception as e:
            error_msg = "[ERROR] DeepSeek API streaming error"
            logging_utility.error(f"{error_msg}: {str(e)}", exc_info=True)
            yield json.dumps({
                'type': 'error',
                'content': error_msg
            })
            return

        if assistant_reply:
            self.message_service.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply,
                role="assistant",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True
            )
            self.run_service.update_run_status(run_id, "completed")
            logging_utility.info("Assistant response stored successfully.")

        if reasoning_content:
            logging_utility.info("Final reasoning content: %s", reasoning_content)
