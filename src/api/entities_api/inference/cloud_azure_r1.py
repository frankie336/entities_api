import json
import os
import time

from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()
logging_utility = LoggingUtility()


class AzureR1Cloud(BaseInference):
    def setup_services(self):
        """Initialize the Azure AI Inference client and other services."""
        self.endpoint = os.getenv(
            "AZURE_ENDPOINT", "https://DeepSeek-R1-pancho.eastus2.models.ai.azure.com"
        )
        self.api_key = (
            "HV6vTsiyIhfis5zPRG4B8b4jI7emEHsw"  # API key from environment variable
        )
        self.client = ChatCompletionsClient(
            endpoint=self.endpoint, credential=AzureKeyCredential(self.api_key)
        )
        logging_utility.info("AzureR1Cloud specific setup completed.")

    def normalize_roles(self, conversation_history):
        """
        Normalize roles to ensure consistency with Azure's API.
        """
        normalized_history = []
        for message in conversation_history:
            role = message.get("role", "").strip().lower()
            if role not in ["user", "assistant", "system"]:
                role = "user"
            normalized_history.append(
                {"role": role, "content": message.get("content", "").strip()}
            )
        return normalized_history

    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model="deepseek-reasoner",
        stream_reasoning=True,
    ):
        """
        Process conversation with dual streaming (content + reasoning).
        """
        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id,
            run_id,
            assistant_id,
        )

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info(
            "Retrieved assistant: id=%s, name=%s, model=%s",
            assistant.id,
            assistant.name,
            assistant.model,
        )

        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        conversation_history = self.normalize_roles(conversation_history)

        messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in conversation_history
        ]

        run_cancelled = False
        assistant_reply = ""
        reasoning_content = ""

        # State management for parsing <think> tags
        buffer = ""
        in_think_block = False

        try:
            # Azure AI Inference request setup
            response = self.client.complete(
                messages=messages,
                stream=True,  # Enable streaming for continuous results
            )

            # Process the streaming response
            for chunk in response:
                try:
                    if chunk.choices:
                        choice = chunk.choices[0].delta
                        content_chunk = choice.get("content", "")

                        # Process content with state management
                        buffer += content_chunk

                        while True:
                            if not in_think_block:
                                # Look for <think> tag
                                think_start = buffer.find("<think>")
                                if think_start == -1:
                                    # Emit all content as regular
                                    if buffer:
                                        yield json.dumps(
                                            {"type": "content", "content": buffer}
                                        )
                                        assistant_reply += buffer
                                    buffer = ""
                                    break

                                # Emit content before <think>
                                if think_start > 0:
                                    yield json.dumps(
                                        {
                                            "type": "content",
                                            "content": buffer[:think_start],
                                        }
                                    )
                                    assistant_reply += buffer[:think_start]

                                # Remove processed content and tag
                                buffer = buffer[
                                    think_start + 7 :
                                ]  # 7 is len('<think>')
                                in_think_block = True

                            if in_think_block:
                                # Look for </think>
                                think_end = buffer.find("</think>")
                                if think_end == -1:
                                    # Emit entire buffer as reasoning
                                    if buffer:
                                        yield json.dumps(
                                            {"type": "reasoning", "content": buffer}
                                        )
                                        reasoning_content += buffer
                                    buffer = ""
                                    break

                                # Emit content until </think>
                                yield json.dumps(
                                    {"type": "reasoning", "content": buffer[:think_end]}
                                )
                                reasoning_content += buffer[:think_end]

                                # Remove processed content and tag
                                buffer = buffer[think_end + 8 :]  # 8 is len('</think>')
                                in_think_block = False

                        time.sleep(0.01)

                    # Check for cancellation during streaming
                    current_run = self.run_service.retrieve_run(run_id)
                    if current_run.status in ["cancelling", "cancelled"]:
                        logging_utility.warning(
                            f"Run {run_id} cancelled during streaming"
                        )
                        run_cancelled = True
                        break

                except KeyError:
                    continue

        except Exception as e:
            error_msg = "[ERROR] Azure API streaming error"
            logging_utility.error(f"{error_msg}: {str(e)}", exc_info=True)
            self.run_service.update_run_status(run_id, "failed")
            yield json.dumps({"type": "error", "content": error_msg})
            return

        # Final flush of remaining buffer
        if buffer:
            if in_think_block:
                yield json.dumps({"type": "reasoning", "content": buffer})
                reasoning_content += buffer
            else:
                yield json.dumps({"type": "content", "content": buffer})
                assistant_reply += buffer

        if run_cancelled:
            self.run_service.update_run_status(run_id, "cancelled")
            # Save partial content
            if assistant_reply:
                self.message_service.save_assistant_message_chunk(
                    role="assistant",
                    thread_id=thread_id,
                    content=assistant_reply,
                    is_last_chunk=True,
                )
            if reasoning_content:
                logging_utility.info(
                    "Saved partial reasoning content: %s", reasoning_content
                )
            return

        # Final state handling for successful completion
        if assistant_reply:
            self.message_service.save_assistant_message_chunk(
                role="assistant",
                thread_id=thread_id,
                content=assistant_reply,
                is_last_chunk=True,
            )
            logging_utility.info("Assistant response stored successfully.")
            self.run_service.update_run_status(run_id, "completed")

        if reasoning_content:
            logging_utility.info("Final reasoning content: %s", reasoning_content)
