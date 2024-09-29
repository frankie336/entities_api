# base_inference.py

from abc import ABC, abstractmethod

class BaseInference(ABC):
    def __init__(self, base_url, api_key, available_functions):
        self.base_url = base_url
        self.api_key = api_key
        self.available_functions = available_functions
        self.setup_services()

    @abstractmethod
    def setup_services(self):
        """
        Initialize and set up all necessary services.
        """
        pass

    @abstractmethod
    def process_conversation(self, *args, **kwargs):
        """
        Process the conversation and yield response chunks.
        """
        pass

    # You can add more abstract methods if there are other common functionalities
