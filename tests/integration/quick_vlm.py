import json

import httpx

r = httpx.post(
    "http://localhost:8001/v1/completions/render",
    json={
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "prompt": "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\nWhat is the weather in London?<|im_end|>\n<|im_start|>assistant\n",
    },
    timeout=10,
)

print(json.dumps(r.json(), indent=2))
