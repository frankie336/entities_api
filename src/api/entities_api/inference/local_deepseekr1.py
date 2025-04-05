import json
import time

from dotenv import load_dotenv
from ollama import Client

from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class DeepSeekR1Local(BaseInference):
    def setup_services(self):

        self.ollama_client = Client()
        logging_utility.info("DeepSeekR1Local specific setup completed.")

    def create_tool_filtering_messages(self, messages):
        logging_utility.info("Creating tool filtering messages")
        logging_utility.debug("Original messages: %s", messages)

        system_message = next((msg for msg in messages if msg['role'] == 'system'), None)
        last_user_message = next((msg for msg in reversed(messages) if msg['role'] == 'user'), None)

        if not system_message or not last_user_message:
            logging_utility.warning("Could not find necessary messages for filtering. Using original messages.")
            return messages  # Return original if we can't find necessary messages

        filtered_messages = [system_message, last_user_message]
        logging_utility.info("Created filtered messages for tool calls")
        logging_utility.debug("Filtered messages: %s", filtered_messages)

        return filtered_messages

    def _process_tool_calls(self, run_id, tool_calls, message_id, thread_id):
        # ... existing method code ...
        tool_results = []
        try:
            for tool in tool_calls:
                function_name = tool['function']['name']
                function_args = tool['function']['arguments']

                logging_utility.info(f"Function call triggered for run_id: {run_id}, function_name: {function_name}")

                # Look up tool by name
                tool_record = self.tool_service.get_tool_by_name(function_name)
                if not tool_record:
                    raise ValueError(f"Tool with name '{function_name}' not found")

                tool_id = tool_record.id  # Use tool_id

                # Create the action for the tool call
                action_response = self.action_service.create_action(
                    tool_name=function_name,
                    run_id=run_id,
                    function_args=function_args
                )

                logging_utility.info(f"Created action for function call: {action_response.id}")

                # Execute the corresponding function
                if function_name in self.available_functions:
                    function_to_call = self.available_functions[function_name]
                    try:
                        function_response = function_to_call(**function_args)
                        parsed_response = json.loads(function_response)

                        # Save the tool response
                        self.message_service.submit_tool_output(message_id, function_response)
                        logging_utility.info(f"Tool response saved to thread: {thread_id}")

                        tool_results.append(parsed_response)  # Collect successful results
                    except Exception as func_e:
                        logging_utility.error(f"Error executing function '{function_name}': {str(func_e)}", exc_info=True)
                        # Do not append the result to tool_results if there's an error
                else:
                    raise ValueError(f"Function '{function_name}' is not available in available_functions")

        except Exception as e:
            logging_utility.error(f"Error in _process_tool_calls: {str(e)}", exc_info=True)

        return tool_results  # Return collected results, excluding any that had errors

    def generate_final_response(self, thread_id, message_id, run_id, tool_results, messages, model):
        logging_utility.info(f"Generating final response for run_id: {run_id}")

        if tool_results:
            messages.extend({'role': 'tool', 'content': json.dumps(r)} for r in tool_results)

        full_response = ""
        run_cancelled = False  # Cancellation state tracker

        try:
            streaming_response = self.ollama_client.chat(
                model=model,
                messages=messages,
                options={'num_ctx': 8000},
                stream=True
            )

            for chunk in streaming_response:
                content = chunk.get('message', {}).get('content', '')
                full_response += content

                # Stream content to client
                yield content

                # Check cancellation status every chunk
                current_status = self.run_service.retrieve_run(run_id).status
                if current_status in ["cancelling", "cancelled"]:
                    # Immediate partial save
                    self.message_service.save_assistant_message_chunk(
                        role='assistant',
                        thread_id=thread_id,
                        content=full_response,
                        is_last_chunk=True
                    )
                    self.run_service.update_run_status(run_id, "cancelled")
                    run_cancelled = True
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    break

                time.sleep(0.01)

            # Final completion handling
            if not run_cancelled:
                self.message_service.save_assistant_message_chunk(
                    role='assistant',
                    thread_id=thread_id,
                    content=full_response,
                    is_last_chunk=True
                )
                self.run_service.update_run_status(run_id, "completed")
                logging_utility.info(f"Completed response for {run_id}")

        except Exception as e:
            logging_utility.error(f"Streaming failure: {str(e)}", exc_info=True)
            # Emergency save of partial response
            if full_response:
                self.message_service.save_assistant_message_chunk(
                    role='assistant',
                    thread_id=thread_id,
                    content=full_response,
                    is_last_chunk=True
                )
            self.run_service.update_run_status(run_id, "failed")
            yield f"[ERROR] Response generation failed: {str(e)}"


    def process_conversation(self, thread_id, message_id, run_id, assistant_id, model='llama3.1'):
        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, model: %s",
            thread_id, run_id, model
        )

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info(
            "Retrieved assistant: id=%s, name=%s, model=%s",
            assistant.id, assistant.name, assistant.model
        )

        messages = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        logging_utility.debug("Original formatted messages: %s", messages)

        tool_filtering_messages = self.create_tool_filtering_messages(messages)
        tool_results = []

        # Initial chat call
        response = self.ollama_client.chat(
            model=model,
            messages=tool_filtering_messages,
            options={'num_ctx': 8000},
            #DeepSeekR1Local does not support tools
        )

        logging_utility.debug("Initial chat response: %s", response)

        if response['message'].get('tool_calls'):
            tool_results = self._process_tool_calls(
                run_id, response['message']['tool_calls'], message_id, thread_id
            )

        # Generate and stream the final response
        return self.generate_final_response(
            thread_id, message_id, run_id, tool_results, messages, model
        )