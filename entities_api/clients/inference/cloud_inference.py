from entities_api.clients.inference.cloud_deepseek_r1 import DeepSeekR1Cloud
from entities_api.clients.inference.cloud_deepseek_v3 import DeepSeekV3Cloud
from entities_api.clients.inference.cloud_groq_deepseekr1_llama import GroqCloud


class CloudInference:
    def __init__(self):
        self._deep_seek_r1 = DeepSeekR1Cloud()
        self._deep_seek_v3 = DeepSeekV3Cloud()
        self._groq = GroqCloud()

    def get_deepseek_r1(self):
        return self._deep_seek_r1

    def get_deepseek_v3(self):
        return self._deep_seek_v3

    def get_groq_deepseek(self):
        return self._groq