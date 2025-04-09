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

    def stream_function_call_output(
        self,
        thread_id,
        run_id,
        assistant_id,
        model,
        name=None,
        stream_reasoning=False,
        api_key: Optional[str] = None,
    ):

        return super().stream_function_call_output(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )

    def stream_response(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=True,
        api_key: Optional[str] = None,
    ):

        return super().stream_hyperbolic(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )

    def process_function_calls(
        self,
        thread_id,
        run_id,
        assistant_id,
        model=None,
        api_key: Optional[str] = None,
    ):

        return super().process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,
        )

    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=False,
        api_key: Optional[str] = None,
    ):
        """
        Processes the conversation, passing the api_key down for use
        in the actual API request via override.
        """

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
            api_key=api_key,
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
