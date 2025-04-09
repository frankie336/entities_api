import time
from typing import Optional

from dotenv import load_dotenv

from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()


class HyperbolicV3Inference(BaseInference):

    def setup_services(self):
        logging_utility.debug(
            "HyperbolicV3Inference specific setup completed (if any)."
        )

    # ... (get_tool_response_state, get_function_call_state, handle_code_interpreter_action - Keep as is) ...

    def stream_function_call_output(
        self,
        thread_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=False,
        api_key: Optional[str] = None,  # Keep parameter signature
    ):
        # Ensure super method accepts api_key if needed
        return super().stream_function_call_output(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,  # <-- PASS api_key to super()
        )

    def stream_response(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=True,
        api_key: Optional[str] = None,  # Keep parameter signature
    ):
        # Pass the key down to the base class method which handles the API call
        return super().stream_hyperbolic(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,  # <-- PASS api_key to super()
        )

    def process_function_calls(
        self,
        thread_id,
        run_id,
        assistant_id,
        model=None,
        api_key: Optional[str] = None,  # Keep parameter signature
    ):
        # Ensure super method accepts api_key if needed
        return super().process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,  # <-- PASS api_key to super()
        )

    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=False,
        api_key: Optional[str] = None,  # Keep parameter signature
    ):
        """
        Processes the conversation, passing the api_key down for use
        in the actual API request via override.
        """
        # --- REMOVE THIS LINE ---
        # self.set_api_key(api_key=api_key)
        # -----------------------

        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)

        logging_utility.info(
            f"Processing conversation for run {run_id} with model {model}. API key provided: {'Yes' if api_key else 'No'}"
        )

        # Stream the response, passing the api_key for override
        for chunk in self.stream_response(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,  # <-- Keep Passing api_key
        ):
            yield chunk

        # Process function calls, passing the api_key if needed by sub-calls
        for chunk in self.process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,  # <-- Keep Passing api_key
        ):
            yield chunk

        logging_utility.info(
            f"Finished processing conversation generator for run {run_id}"
        )
