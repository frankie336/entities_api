# inference_factory.py

import os
from entities_api.new_clients.inference.local_inference import LocalInference
from entities_api.new_clients.inference.cloud_inference import CloudInference
from entities_api.services.logging_service import LoggingUtility

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
            logging_utility.info("Creating LocalInference instance.")
            return LocalInference(base_url=base_url, api_key=api_key, available_functions=available_functions)
        elif inference_type.lower() == 'cloud':
            logging_utility.info("Creating CloudInference instance.")
            return CloudInference(base_url=base_url, api_key=api_key, available_functions=available_functions)
        else:
            logging_utility.error(f"Unknown inference type: {inference_type}")
            raise ValueError(f"Unknown inference type: {inference_type}")
