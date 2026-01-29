# models.py

# ... imports ...

# --- TOGETHER_AI_MODELS_START ---
TOGETHER_AI_MODELS = {
    # --- Qwen ---
    "Qwen2.5-14B-Instruct": {
        "id": "together-ai/Qwen/Qwen2.5-14B-Instruct",
        "provider": "together-ai",
    },
    "Qwen2.5-72B-Instruct": {
        "id": "together-ai/Qwen/Qwen2.5-72B-Instruct",
        "provider": "together-ai",
    },
    "Qwen2.5-72B-Instruct-Turbo": {
        "id": "together-ai/Qwen/Qwen2.5-72B-Instruct-Turbo",
        "provider": "together-ai",
    },
    "Qwen2.5-7B-Instruct-Turbo": {
        "id": "together-ai/Qwen/Qwen2.5-7B-Instruct-Turbo",
        "provider": "together-ai",
    },
    "Qwen2.5-VL-72B-Instruct": {
        "id": "together-ai/Qwen/Qwen2.5-VL-72B-Instruct",
        "provider": "together-ai",
    },
    "Qwen3-235B-A22B-Instruct-2507-tput": {
        "id": "together-ai/Qwen/Qwen3-235B-A22B-Instruct-2507-tput",
        "provider": "together-ai",
    },
    "Qwen3-235B-A22B-Thinking-2507": {
        "id": "together-ai/Qwen/Qwen3-235B-A22B-Thinking-2507",
        "provider": "together-ai",
    },
    "Qwen3-235B-A22B-fp8-tput": {
        "id": "together-ai/Qwen/Qwen3-235B-A22B-fp8-tput",
        "provider": "together-ai",
    },
    "Qwen3-Coder-480B-A35B-Instruct-FP8": {
        "id": "together-ai/Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
        "provider": "together-ai",
    },
    "Qwen3-Next-80B-A3B-Instruct": {
        "id": "together-ai/Qwen/Qwen3-Next-80B-A3B-Instruct",
        "provider": "together-ai",
    },
    "Qwen3-Next-80B-A3B-Thinking": {
        "id": "together-ai/Qwen/Qwen3-Next-80B-A3B-Thinking",
        "provider": "together-ai",
    },
    "Qwen3-VL-32B-Instruct": {
        "id": "together-ai/Qwen/Qwen3-VL-32B-Instruct",
        "provider": "together-ai",
    },
    "Qwen3-VL-8B-Instruct": {
        "id": "together-ai/Qwen/Qwen3-VL-8B-Instruct",
        "provider": "together-ai",
    },
    # --- ServiceNow-AI ---
    "Apriel-1.5-15b-Thinker": {
        "id": "together-ai/ServiceNow-AI/Apriel-1.5-15b-Thinker",
        "provider": "together-ai",
    },
    "Apriel-1.6-15b-Thinker": {
        "id": "together-ai/ServiceNow-AI/Apriel-1.6-15b-Thinker",
        "provider": "together-ai",
    },
    # --- arcee-ai ---
    "trinity-mini": {
        "id": "together-ai/arcee-ai/trinity-mini",
        "provider": "together-ai",
    },
    # --- arize-ai ---
    "qwen-2-1.5b-instruct": {
        "id": "together-ai/arize-ai/qwen-2-1.5b-instruct",
        "provider": "together-ai",
    },
    # --- deepcogito ---
    "cogito-v2-1-671b": {
        "id": "together-ai/deepcogito/cogito-v2-1-671b",
        "provider": "together-ai",
    },
    "cogito-v2-preview-llama-109B-MoE": {
        "id": "together-ai/deepcogito/cogito-v2-preview-llama-109B-MoE",
        "provider": "together-ai",
    },
    "cogito-v2-preview-llama-405B": {
        "id": "together-ai/deepcogito/cogito-v2-preview-llama-405B",
        "provider": "together-ai",
    },
    "cogito-v2-preview-llama-70B": {
        "id": "together-ai/deepcogito/cogito-v2-preview-llama-70B",
        "provider": "together-ai",
    },
    # --- deepseek-ai ---
    "DeepSeek-R1": {
        "id": "together-ai/deepseek-ai/DeepSeek-R1",
        "provider": "together-ai",
    },
    "DeepSeek-R1-0528-tput": {
        "id": "together-ai/deepseek-ai/DeepSeek-R1-0528-tput",
        "provider": "together-ai",
    },
    "DeepSeek-R1-Distill-Llama-70B": {
        "id": "together-ai/deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
        "provider": "together-ai",
    },
    "DeepSeek-V3.1": {
        "id": "together-ai/deepseek-ai/DeepSeek-V3.1",
        "provider": "together-ai",
    },
    # --- essentialai ---
    "rnj-1-instruct": {
        "id": "together-ai/essentialai/rnj-1-instruct",
        "provider": "together-ai",
    },
    # --- google ---
    "gemma-2b-it-Ishan": {
        "id": "together-ai/google/gemma-2b-it-Ishan",
        "provider": "together-ai",
    },
    "gemma-3n-E4B-it": {
        "id": "together-ai/google/gemma-3n-E4B-it",
        "provider": "together-ai",
    },
    # --- marin-community ---
    "marin-8b-instruct": {
        "id": "together-ai/marin-community/marin-8b-instruct",
        "provider": "together-ai",
    },
    # --- meta-llama ---
    "Llama-3-70b-hf": {
        "id": "together-ai/meta-llama/Llama-3-70b-hf",
        "provider": "together-ai",
    },
    "Llama-3.1-405B-Instruct": {
        "id": "together-ai/meta-llama/Llama-3.1-405B-Instruct",
        "provider": "together-ai",
    },
    "Llama-3.2-1B-Instruct": {
        "id": "together-ai/meta-llama/Llama-3.2-1B-Instruct",
        "provider": "together-ai",
    },
    "Llama-3.2-3B-Instruct-Turbo": {
        "id": "together-ai/meta-llama/Llama-3.2-3B-Instruct-Turbo",
        "provider": "together-ai",
    },
    "Llama-3.3-70B-Instruct-Turbo": {
        "id": "together-ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "provider": "together-ai",
    },
    "Llama-4-Maverick-17B-128E-Instruct-FP8": {
        "id": "together-ai/meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
        "provider": "together-ai",
    },
    "Llama-4-Scout-17B-16E-Instruct": {
        "id": "together-ai/meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "provider": "together-ai",
    },
    "Meta-Llama-3-8B-Instruct": {
        "id": "together-ai/meta-llama/Meta-Llama-3-8B-Instruct",
        "provider": "together-ai",
    },
    "Meta-Llama-3-8B-Instruct-Lite": {
        "id": "together-ai/meta-llama/Meta-Llama-3-8B-Instruct-Lite",
        "provider": "together-ai",
    },
    "Meta-Llama-3.1-405B-Instruct-Turbo": {
        "id": "together-ai/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
        "provider": "together-ai",
    },
    "Meta-Llama-3.1-70B-Instruct-Reference": {
        "id": "together-ai/meta-llama/Meta-Llama-3.1-70B-Instruct-Reference",
        "provider": "together-ai",
    },
    "Meta-Llama-3.1-70B-Instruct-Turbo": {
        "id": "together-ai/meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "provider": "together-ai",
    },
    "Meta-Llama-3.1-8B-Instruct-Reference": {
        "id": "together-ai/meta-llama/Meta-Llama-3.1-8B-Instruct-Reference",
        "provider": "together-ai",
    },
    "Meta-Llama-3.1-8B-Instruct-Turbo": {
        "id": "together-ai/meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "provider": "together-ai",
    },
    # --- mistralai ---
    "Ministral-3-14B-Instruct-2512": {
        "id": "together-ai/mistralai/Ministral-3-14B-Instruct-2512",
        "provider": "together-ai",
    },
    "Mistral-7B-Instruct-v0.2": {
        "id": "together-ai/mistralai/Mistral-7B-Instruct-v0.2",
        "provider": "together-ai",
    },
    "Mistral-7B-Instruct-v0.3": {
        "id": "together-ai/mistralai/Mistral-7B-Instruct-v0.3",
        "provider": "together-ai",
    },
    "Mistral-Small-24B-Instruct-2501": {
        "id": "together-ai/mistralai/Mistral-Small-24B-Instruct-2501",
        "provider": "together-ai",
    },
    "Mixtral-8x7B-Instruct-v0.1": {
        "id": "together-ai/mistralai/Mixtral-8x7B-Instruct-v0.1",
        "provider": "together-ai",
    },
    # --- moonshotai ---
    "Kimi-K2-Instruct-0905": {
        "id": "together-ai/moonshotai/Kimi-K2-Instruct-0905",
        "provider": "together-ai",
    },
    "Kimi-K2-Thinking": {
        "id": "together-ai/moonshotai/Kimi-K2-Thinking",
        "provider": "together-ai",
    },
    # --- nvidia ---
    "NVIDIA-Nemotron-Nano-9B-v2": {
        "id": "together-ai/nvidia/NVIDIA-Nemotron-Nano-9B-v2",
        "provider": "together-ai",
    },
    # --- openai ---
    "gpt-oss-120b": {
        "id": "together-ai/openai/gpt-oss-120b",
        "provider": "together-ai",
    },
    "gpt-oss-20b": {
        "id": "together-ai/openai/gpt-oss-20b",
        "provider": "together-ai",
    },
    # --- scb10x ---
    "scb10x-typhoon-2-1-gemma3-12b": {
        "id": "together-ai/scb10x/scb10x-typhoon-2-1-gemma3-12b",
        "provider": "together-ai",
    },
    # --- togethercomputer ---
    "MoA-1": {
        "id": "together-ai/togethercomputer/MoA-1",
        "provider": "together-ai",
    },
    "MoA-1-Turbo": {
        "id": "together-ai/togethercomputer/MoA-1-Turbo",
        "provider": "together-ai",
    },
    "Refuel-Llm-V2": {
        "id": "together-ai/togethercomputer/Refuel-Llm-V2",
        "provider": "together-ai",
    },
    "Refuel-Llm-V2-Small": {
        "id": "together-ai/togethercomputer/Refuel-Llm-V2-Small",
        "provider": "together-ai",
    },
    # --- zai-org ---
    "GLM-4.5-Air-FP8": {
        "id": "together-ai/zai-org/GLM-4.5-Air-FP8",
        "provider": "together-ai",
    },
    "GLM-4.6": {
        "id": "together-ai/zai-org/GLM-4.6",
        "provider": "together-ai",
    },
    "GLM-4.7": {
        "id": "together-ai/zai-org/GLM-4.7",
        "provider": "together-ai",
    },
}


# --- HYPERBOLIC_MODELS_START ---
HYPERBOLIC_MODELS = {
    # --- Qwen ---
    "QwQ-32B": {
        "id": "hyperbolic/Qwen/QwQ-32B",
        "provider": "hyperbolic",
    },
    "Qwen2.5-72B-Instruct": {
        "id": "hyperbolic/Qwen/Qwen2.5-72B-Instruct",
        "provider": "hyperbolic",
    },
    "Qwen2.5-Coder-32B-Instruct": {
        "id": "hyperbolic/Qwen/Qwen2.5-Coder-32B-Instruct",
        "provider": "hyperbolic",
    },
    "Qwen2.5-VL-72B-Instruct": {
        "id": "hyperbolic/Qwen/Qwen2.5-VL-72B-Instruct",
        "provider": "hyperbolic",
    },
    "Qwen2.5-VL-7B-Instruct": {
        "id": "hyperbolic/Qwen/Qwen2.5-VL-7B-Instruct",
        "provider": "hyperbolic",
    },
    "Qwen3-235B-A22B": {
        "id": "hyperbolic/Qwen/Qwen3-235B-A22B",
        "provider": "hyperbolic",
    },
    "Qwen3-235B-A22B-Instruct-2507": {
        "id": "hyperbolic/Qwen/Qwen3-235B-A22B-Instruct-2507",
        "provider": "hyperbolic",
    },
    "Qwen3-Coder-480B-A35B-Instruct": {
        "id": "hyperbolic/Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "provider": "hyperbolic",
    },
    "Qwen3-Next-80B-A3B-Instruct": {
        "id": "hyperbolic/Qwen/Qwen3-Next-80B-A3B-Instruct",
        "provider": "hyperbolic",
    },
    "Qwen3-Next-80B-A3B-Thinking": {
        "id": "hyperbolic/Qwen/Qwen3-Next-80B-A3B-Thinking",
        "provider": "hyperbolic",
    },
    # --- deepseek-ai ---
    "DeepSeek-R1": {
        "id": "hyperbolic/deepseek-ai/DeepSeek-R1",
        "provider": "hyperbolic",
    },
    "DeepSeek-R1-0528": {
        "id": "hyperbolic/deepseek-ai/DeepSeek-R1-0528",
        "provider": "hyperbolic",
    },
    "DeepSeek-V3": {
        "id": "hyperbolic/deepseek-ai/DeepSeek-V3",
        "provider": "hyperbolic",
    },
    "DeepSeek-V3-0324": {
        "id": "hyperbolic/deepseek-ai/DeepSeek-V3-0324",
        "provider": "hyperbolic",
    },
    # --- meta-llama ---
    "Llama-3.2-3B-Instruct": {
        "id": "hyperbolic/meta-llama/Llama-3.2-3B-Instruct",
        "provider": "hyperbolic",
    },
    "Llama-3.3-70B-Instruct": {
        "id": "hyperbolic/meta-llama/Llama-3.3-70B-Instruct",
        "provider": "hyperbolic",
    },
    "Meta-Llama-3.1-405B": {
        "id": "hyperbolic/meta-llama/Meta-Llama-3.1-405B",
        "provider": "hyperbolic",
    },
    "Meta-Llama-3.1-405B-Instruct": {
        "id": "hyperbolic/meta-llama/Meta-Llama-3.1-405B-Instruct",
        "provider": "hyperbolic",
    },
    "Meta-Llama-3.1-70B-Instruct": {
        "id": "hyperbolic/meta-llama/Meta-Llama-3.1-70B-Instruct",
        "provider": "hyperbolic",
    },
    "Meta-Llama-3.1-8B-Instruct": {
        "id": "hyperbolic/meta-llama/Meta-Llama-3.1-8B-Instruct",
        "provider": "hyperbolic",
    },
    # --- mistralai ---
    "Pixtral-12B-2409": {
        "id": "hyperbolic/mistralai/Pixtral-12B-2409",
        "provider": "hyperbolic",
    },
    # --- openai ---
    "gpt-oss-120b": {
        "id": "hyperbolic/openai/gpt-oss-120b",
        "provider": "hyperbolic",
    },
    "gpt-oss-120b-turbo": {
        "id": "hyperbolic/openai/gpt-oss-120b-turbo",
        "provider": "hyperbolic",
    },
    "gpt-oss-20b": {
        "id": "hyperbolic/openai/gpt-oss-20b",
        "provider": "hyperbolic",
    },
}
