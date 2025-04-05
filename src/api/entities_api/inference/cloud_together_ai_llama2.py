from abc import ABC

from dotenv import load_dotenv
from entities_common import UtilsInterface

from entities_api.inference.base_inference import BaseInference

load_dotenv()
logging_utility = UtilsInterface.LoggingUtility()

class TogetherLlama2Inference(BaseInference, ABC):

    def setup_services(self):
        """
        Initialize the DeepSeek client and other services.
        """
    def get_tool_response_state(self):
        return self.tool_response

    def get_function_call_state(self):
        return self.function_call


    def handle_code_interpreter_action(self, thread_id, run_id, assistant_id, arguments_dict):
        return super().handle_code_interpreter_action(thread_id, run_id, assistant_id, arguments_dict)


    def stream_response(self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=True):
        return super().stream_response_together(thread_id, message_id, run_id, assistant_id, model,
                                                  stream_reasoning=True)

    def process_function_calls(self, thread_id, run_id, assistant_id, model=None):
        return super().process_function_calls(thread_id, run_id, assistant_id, model=None)

    def process_conversation(self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=False):

        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)

        # Stream the response and yield each chunk.
        for chunk in self.stream_response(thread_id, message_id, run_id, assistant_id, model, stream_reasoning):
            yield chunk
        # Process function call state using the centralized method.
        for chunk in self.process_function_calls(thread_id, run_id, assistant_id, model=model):
            yield chunk



    def __del__(self):
        """Cleanup resources."""
        super().__del__()
