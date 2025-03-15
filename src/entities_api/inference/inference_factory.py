# inference_factory.py
import os
from src.entities_api.inference.llama_local import LlamaLocal
from src.entities_api.inference.groq_inference import CloudInference
from src.entities_api.services.logging_service import LoggingUtility

# Initialize logging utility
logging_utility = LoggingUtility()


class InferenceFactory:
    @staticmethod
    def get_inference(inference_type, available_functions=None):
        """
        Factory method to get the appropriate Inference instance.

        Args:
            inference_type (str): Type of inference ('local' or 'cloud').
            available_functions (dict): Available functions for tool calls.

        Returns:
            BaseInference: An instance of a class inheriting from BaseInference.

        Raises:
            ValueError: If an unknown inference_type is provided.
        """
        base_url = os.getenv('ASSISTANTS_BASE_URL')
        api_key = os.getenv('API_KEY')

        if inference_type.lower() == 'local':
            logging_utility.info("Creating DeepSeekR1Local instance.")
            return LlamaLocal(base_url=base_url, api_key=api_key, available_functions=available_functions)
        elif inference_type.lower() == 'cloud':
            logging_utility.info("Creating CloudInference instance.")
            return CloudInference(base_url=base_url, api_key=api_key, available_functions=available_functions)
        else:
            logging_utility.error(f"Unknown inference type: {inference_type}")
            raise ValueError(f"Unknown inference type: {inference_type}")
