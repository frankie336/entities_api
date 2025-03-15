import json
import time
import logging

from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)


class AzureR1Cloud:
    def setup_services(self):
        """Initialize the Azure AI Inference client."""
        self.endpoint = "https://test7059065274.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview"
        self.api_key = "DHMf5ACazFqVKSPUvRzLFKPC6b250C5s6vk6eHzMbqlQePMMYvFrJQQJ99BAACHYHv6XJ3w3AAAAACOGc3dI"
        self.client = ChatCompletionsClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.api_key)
        )
        logging.info("AzureR1Cloud setup completed.")

    def process_conversation(self, messages, stream_reasoning=True):
        """
        Process conversation with dual streaming (content + reasoning).
        """
        logging.info("Processing conversation...")

        run_cancelled = False
        assistant_reply = ""
        reasoning_content = ""

        try:
            # Azure AI Inference request setup
            response = self.client.complete(
                messages=messages,
                stream=True  # Enable streaming for continuous results
            )

            # Process the streaming response
            for chunk in response:
                try:
                    # Streaming chunk handling
                    if chunk.choices:
                        choice = chunk.choices[0].delta

                        if 'reasoning_content' in choice:
                            reasoning_chunk = choice['reasoning_content']
                            reasoning_content += reasoning_chunk
                            yield json.dumps({'type': 'reasoning', 'content': reasoning_chunk})

                        if 'content' in choice:
                            content_chunk = choice['content']
                            assistant_reply += content_chunk
                            yield json.dumps({'type': 'content', 'content': content_chunk})

                    time.sleep(0.01)

                except KeyError:
                    continue

        except Exception as e:
            error_msg = "[ERROR] Azure API streaming error"
            logging.error(f"{error_msg}: {str(e)}", exc_info=True)
            yield json.dumps({'type': 'error', 'content': error_msg})
            return

        if run_cancelled:
            logging.info("Run was cancelled during streaming")
            return

        # Final state handling for successful completion
        if assistant_reply:
            logging.info("Assistant response stored successfully.")

        if reasoning_content:
            logging.info("Final reasoning content: %s", reasoning_content)


if __name__ == "__main__":
    # Set up a test environment
    azure_inference = AzureR1Cloud()
    azure_inference.setup_services()

    # Simulated user input message
    messages = [
        {"role": "user", "content": "Hello, how are you?"},  # Example user message
        {"role": "assistant", "content": "I'm doing well, thank you!"}  # Example assistant message
    ]

    # Run a mock test for conversation processing
    for response in azure_inference.process_conversation(messages):
        print(response)
