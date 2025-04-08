import json
import os
import time

from dotenv import load_dotenv
from groq import Groq

from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class GroqCloud(BaseInference):
    def setup_services(self):
        """
        Initialize the Groq client and services.
        """
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        logging_utility.info("GroqCloud specific setup completed.")

    def normalize_roles(self, conversation_history):
        """Normalize roles to ensure API compatibility."""
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
        model="mixtral-8x7b-32768",
        stream_reasoning=True,
    ):
        """
        Process conversation with XML-style reasoning/content streaming.
        """
        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id,
            run_id,
            assistant_id,
        )

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        conversation_history = self.normalize_roles(conversation_history)
        groq_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in conversation_history
        ]

        # Initialize state variables
        assistant_reply = ""
        reasoning_content = ""
        content_buffer = ""
        in_think_block = False
        run_cancelled = False

        try:
            stream_response = self.groq_client.chat.completions.create(
                model=model,
                messages=groq_messages,
                temperature=0.6,
                stream=True,
            )

            for chunk in stream_response:
                # Check for run cancellation
                current_run = self.run_service.retrieve_run(run_id)
                if current_run.status in ["cancelling", "cancelled"]:
                    logging_utility.warning(f"Run {run_id} cancelled during streaming")
                    run_cancelled = True
                    break

                chunk_content = chunk.choices[0].delta.content or ""
                content_buffer += chunk_content

                while True:
                    if not in_think_block:
                        think_start = content_buffer.find("<think>")
                        if think_start != -1:
                            if think_start > 0:
                                content_part = content_buffer[:think_start]
                                yield json.dumps(
                                    {"type": "content", "content": content_part}
                                )
                                assistant_reply += content_part
                            content_buffer = content_buffer[think_start + 7 :]
                            in_think_block = True
                        else:
                            if content_buffer:
                                yield json.dumps(
                                    {"type": "content", "content": content_buffer}
                                )
                                assistant_reply += content_buffer
                                content_buffer = ""
                            break
                    else:
                        think_end = content_buffer.find("</think>")
                        if think_end != -1:
                            reasoning_part = content_buffer[:think_end]
                            yield json.dumps(
                                {"type": "reasoning", "content": reasoning_part}
                            )
                            reasoning_content += reasoning_part
                            content_buffer = content_buffer[think_end + 8 :]
                            in_think_block = False
                        else:
                            if content_buffer:
                                yield json.dumps(
                                    {"type": "reasoning", "content": content_buffer}
                                )
                                reasoning_content += content_buffer
                                content_buffer = ""
                            break
                    time.sleep(0.005)

            # Process remaining content after stream ends
            if content_buffer:
                if in_think_block:
                    yield json.dumps({"type": "reasoning", "content": content_buffer})
                    reasoning_content += content_buffer
                else:
                    yield json.dumps({"type": "content", "content": content_buffer})
                    assistant_reply += content_buffer

        except Exception as e:
            # Handle remaining buffer content on error
            if content_buffer:
                if in_think_block:
                    reasoning_content += content_buffer
                else:
                    assistant_reply += content_buffer
                content_buffer = ""

            error_msg = f"Groq API error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)

            if assistant_reply:
                self.message_service.save_assistant_message_chunk(
                    thread_id=thread_id,
                    content=assistant_reply.strip(),
                    role="assistant",
                    is_last_chunk=True,
                )

            self.run_service.update_run_status(run_id, "failed")
            yield json.dumps({"type": "error", "content": error_msg})
            return

        # Final message persistence
        if assistant_reply:
            self.message_service.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply.strip(),
                role="assistant",
                is_last_chunk=True,
            )

        # Update run status after processing all content
        if run_cancelled:
            self.run_service.update_run_status(run_id, "cancelled")
            logging_utility.info(f"Run {run_id} cancelled with partial response")
        elif assistant_reply:
            self.run_service.update_run_status(run_id, "completed")

        if reasoning_content:
            logging_utility.debug(
                "Final reasoning context: %s", reasoning_content.strip()
            )
