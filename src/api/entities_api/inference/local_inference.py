from entities_api.inference.llama_local import LlamaLocal
from entities_api.inference.local_deepseekr1 import DeepSeekR1Local


class LocalInference:

    def __init__(self):
        self._llama = LlamaLocal()
        self.deep_seekr1 = DeepSeekR1Local()

    def get_llama(self):
        return self._llama

    def get_deepseek_r1(self):
        return self.deep_seekr1
