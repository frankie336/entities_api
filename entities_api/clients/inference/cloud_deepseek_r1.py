import os
import json
import time
from dotenv import load_dotenv
from openai import OpenAI
from entities_api.clients.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()

class DeepSeekR1Cloud(BaseInference):
    def setup_services(self):
        """
        Initialize the DeepSeek client and other services.
        """
        self.deepseek_client = OpenAI(
            api_key="sk-33b3dbc54dd7408793117d410788acbf",
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

        run_cancelled = False
        assistant_reply = ""
        reasoning_content = ""

        try:
            stream_response = self.deepseek_client.chat.completions.create(
                model=model,
                messages=deepseek_messages,
                stream=True,
                temperature=0.3
            )

            for chunk in stream_response:
                # Check for cancellation before processing each chunk
                current_run = self.run_service.retrieve_run(run_id)
                if current_run.status in ["cancelling", "cancelled"]:
                    logging_utility.warning(f"Run {run_id} cancelled during streaming")
                    run_cancelled = True
                    break

                # Existing chunk processing logic
                reasoning_chunk = getattr(chunk.choices[0].delta, 'reasoning_content', '')
                if reasoning_chunk:
                    reasoning_content += reasoning_chunk
                    yield json.dumps({'type': 'reasoning', 'content': reasoning_chunk})

                content_chunk = getattr(chunk.choices[0].delta, 'content', '')
                if content_chunk:
                    assistant_reply += content_chunk
                    yield json.dumps({'type': 'content', 'content': content_chunk})

                time.sleep(0.01)

            # Handle cancellation after stream breaks
            if run_cancelled:
                self.run_service.update_run_status(run_id, "cancelled")
                # Save partial content
                if assistant_reply:
                    self.message_service.save_assistant_message_chunk(
                        role='assistant',
                        thread_id=thread_id,
                        content=assistant_reply,
                        is_last_chunk=True
                    )
                if reasoning_content:
                    logging_utility.info("Saved partial reasoning content: %s", reasoning_content)
                return

        except Exception as e:
            error_msg = "[ERROR] DeepSeek API streaming error"
            logging_utility.error(f"{error_msg}: {str(e)}", exc_info=True)
            self.run_service.update_run_status(run_id, "failed")
            yield json.dumps({'type': 'error', 'content': error_msg})
            return

        # Final state handling for successful completion
        if assistant_reply:
            self.message_service.save_assistant_message_chunk(
                role='assistant',
                thread_id=thread_id,
                content=assistant_reply,
                is_last_chunk=True
            )
            logging_utility.info("Assistant response stored successfully.")
            self.run_service.update_run_status(run_id, "completed")

        if reasoning_content:
            logging_utility.info("Final reasoning content: %s", reasoning_content)