from typing import List, Dict, Optional, Any
import ollama  # Ensure the ollama library is installed
import logging

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OllamaService:
    def __init__(self):
        """
        Initialize the OllamaService.
        """
        pass

    def list_models(self) -> List[Dict[str, Any]]:
        """
        List all available local Ollama models.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing model details.
        """
        try:
            models = ollama.list()
            return models.get("models", [])
        except Exception as e:
            logger.error(f"Failed to list Ollama models: {e}")
            raise RuntimeError("Failed to list Ollama models")

    def pull_model(self, model_name: str) -> Dict[str, Any]:
        """
        Pull a model from the Ollama library.

        Args:
            model_name (str): The name of the model to pull (e.g., "llama2").

        Returns:
            Dict[str, Any]: The response from the API, or None if the request fails.
        """
        try:
            response = ollama.pull(model_name)
            return response
        except Exception as e:
            logger.error(f"Failed to pull model '{model_name}': {e}")
            raise RuntimeError(f"Failed to pull model '{model_name}'")

    def delete_model(self, model_name: str) -> bool:
        """
        Delete a local model.

        Args:
            model_name (str): The name of the model to delete (e.g., "llama2").

        Returns:
            bool: True if the model was deleted successfully, False otherwise.
        """
        try:
            ollama.delete(model_name)
            return True
        except Exception as e:
            logger.error(f"Failed to delete model '{model_name}': {e}")
            raise RuntimeError(f"Failed to delete model '{model_name}'")

    def generate_response(self, model_name: str, prompt: str, **kwargs) -> str:
        """
        Generate a response using a specific Ollama model.

        Args:
            model_name (str): The name of the model to use (e.g., "llama2").
            prompt (str): The input prompt for the model.
            **kwargs: Additional options for the model (e.g., temperature, max_tokens).

        Returns:
            str: The generated response from the model.
        """
        try:
            response = ollama.generate(model=model_name, prompt=prompt, options=kwargs)
            return response.get("response", "")
        except Exception as e:
            logger.error(f"Failed to generate response: {e}")
            raise RuntimeError("Failed to generate response")

    def show_model_info(self, model_name: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific model.

        Args:
            model_name (str): The name of the model to inspect (e.g., "llama2").

        Returns:
            Dict[str, Any]: The model information, or None if the request fails.
        """
        try:
            response = ollama.show(model_name)
            return response
        except Exception as e:
            logger.error(f"Failed to fetch info for model '{model_name}': {e}")
            raise RuntimeError(f"Failed to fetch info for model '{model_name}'")

    def copy_model(self, source_name: str, target_name: str) -> bool:
        """
        Copy a model to a new name.

        Args:
            source_name (str): The name of the source model (e.g., "llama2").
            target_name (str): The name of the new model copy.

        Returns:
            bool: True if the model was copied successfully, False otherwise.
        """
        try:
            ollama.copy(source_name, target_name)
            return True
        except Exception as e:
            logger.error(f"Failed to copy model '{source_name}' to '{target_name}': {e}")
            raise RuntimeError(f"Failed to copy model '{source_name}' to '{target_name}'")

    def model_exists(self, model_name: str) -> bool:
        """
        Check if a model exists locally.

        Args:
            model_name (str): The name of the model to check.

        Returns:
            bool: True if the model exists, False otherwise.
        """
        models = self.list_models()
        return any(model["name"] == model_name for model in models)