from entities_api.clients.inference.llama_local import LlamaLocal
from entities_api.clients.inference.local_deepseekr1 import DeepSeekR1Local



class LocalInference:

    def __init__(self):
        self.llama = LlamaLocal()
        self.deep_seekr1 = DeepSeekR1Local()


    def llama(self):
        return self.llama

    def deep_seekr1(self):
        return self.deep_seekr1