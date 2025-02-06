# entities_api/clients/inference/cloud_hyperbolic_v3.py
import json

from .hyperbolic_base import HyperbolicBaseInference


class HyperbolicV3Inference(HyperbolicBaseInference):
    DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3"
    DEFAULT_TEMPERATURE = 0.1

    def process_line(self, line):
        """Simplified V3 processing without reasoning"""
        if not line or line == "[DONE]":
            return None

        line = line[len("data:"):].strip() if line.startswith("data:") else line

        try:
            chunk = json.loads(line)
            content = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
            if content:
                return json.dumps({'type': 'content', 'content': content})
        except json.JSONDecodeError:
            return None