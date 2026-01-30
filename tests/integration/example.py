from projectdavid_common.constants.ai_model_map import TOGETHER_AI_MODELS


"""
The dictionary I have imported from our shared module looks like this:

TOGETHER_AI_MODELS = {
    # --- DeepSeek ---
    "together-ai/deepseek-ai/DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
    "together-ai/deepseek-ai/DeepSeek-R1-0528-tput": "deepseek-ai/DeepSeek-R1-0528-tput",
    "together-ai/deepseek-ai/DeepSeek-V3": "deepseek-ai/DeepSeek-V3",
    "together-ai/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
    "together-ai/deepseek-ai/deepseek-ai/DeepSeek-R1-Distill-Qwen-14B": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B",
    "together-ai/deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free": "deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free",
    ""

    # --- Meta Llama ---
    "together-ai/meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    "together-ai/meta-llama/Llama-4-Scout-17B-16E-Instruct": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "together-ai/meta-llama/Llama-3.3-70B-Instruct-Turbo": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "together-ai/meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo": "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
    "together-ai/meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo": "meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo",
    "together-ai/meta-llama/Llama-Vision-Free": "meta-llama/Llama-Vision-Free",
    "together-ai/meta-llama/LlamaGuard-2-8b": "meta-llama/LlamaGuard-2-8b",
    "together-ai/meta-llama/Llama-3-70b-hf": "meta-llama/Llama-3-70b-hf",



    # --- Google ---
    "together-ai/google/gemma-2-9b-it": "google/gemma-2-9b-it",
    # --- Mistral ---
    "together-ai/mistralai/Mistral-7B-Instruct-v0.2": "mistralai/Mistral-7B-Instruct-v0.2",
    "together-ai/mistralai/Mistral-7B-Instruct-v0.3": "mistralai/Mistral-7B-Instruct-v0.3",
    # --- Qwen (Legacy/Existing) ---
    "together-ai/Qwen/QwQ-32B": "Qwen/QwQ-32B",
    "together-ai/Qwen/Qwen2.5-Coder-32B-Instruct": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "together-ai/Qwen/Qwen2-VL-72B-Instruct": "Qwen/Qwen2-VL-72B-Instruct",
    # --- Qwen (New Additions) ---
    # Qwen 3 Series
    "together-ai/Qwen/Qwen3-Next-80B-A3B-Instruct": "Qwen/Qwen3-Next-80B-A3B-Instruct",
    "together-ai/Qwen/Qwen3-Next-80B-A3B-Thinking": "Qwen/Qwen3-Next-80B-A3B-Thinking",
    "together-ai/Qwen/Qwen3-Next-80B-A3B-Instruct-FP8": "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
    "together-ai/Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8": "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
    "together-ai/Qwen/Qwen3-235B-A22B-Instruct-2507-tput": "Qwen/Qwen3-235B-A22B-Instruct-2507-tput",
    "together-ai/Qwen/Qwen3-235B-A22B-fp8-tput": "Qwen/Qwen3-235B-A22B-fp8-tput",
    "together-ai/Qwen/Qwen3-235B-A22B-Thinking-2507": "Qwen/Qwen3-235B-A22B-Thinking-2507",
    "together-ai/Qwen/Qwen3-VL-8B-Instruct": "Qwen/Qwen3-VL-8B-Instruct",
    "together-ai/Qwen/Qwen3-VL-32B-Instruct": "Qwen/Qwen3-VL-32B-Instruct",
    "together-ai/Qwen/Qwen3-VL-235B-A22B-Instruct-FP": "Qwen/Qwen3-VL-235B-A22B-Instruct-FP",
    "together-ai/Qwen/Qwen3-8B": "Qwen/Qwen3-8B",
    "together-ai/Qwen/Qwen3-14B-Base": "Qwen/Qwen3-14B-Base",

    # Qwen 2.5 Series
    "together-ai/Qwen/Qwen2.5-72B-Instruct": "Qwen/Qwen2.5-72B-Instruct",
    "together-ai/Qwen/Qwen2.5-72B-Instruct-Turbo": "Qwen/Qwen2.5-72B-Instruct-Turbo",
    "together-ai/Qwen/Qwen2.5-VL-72B-Instruct": "Qwen/Qwen2.5-VL-72B-Instruct",
    "together-ai/Qwen/Qwen2.5-7B-Instruct-Turbo": "Qwen/Qwen2.5-7B-Instruct-Turbo",
    "together-ai/Qwen/Qwen2.5-1.5B": "Qwen/Qwen2.5-1.5B",
    # Misc
    "together-ai/Qwen/Qwen-Image": "Qwen/Qwen-Image",
    "together-ai/Qwen/Qwen2-7B": "Qwen/Qwen2-7B",
    # OpenAI
    "together-ai/openai/gpt-oss-120b": "openai/gpt-oss-120b",
    "together-ai/openai/gpt-oss-20b": "openai/gpt-oss-20b",

    # Nvidia
   "together-ai/nvidia/NVIDIA-Nemotron-Nano-9B-v2": "nvidia/NVIDIA-Nemotron-Nano-9B",

    # ServiceNow
    "together-ai/ServiceNow-AI/Apriel-1.5-15b-Thinker": "ServiceNow-AI/Apriel-1.5-15b-Thinker",



}
Ok good, you will see that we use it to map third party endpoints to our strings,

using the pattern that you have observed


We need to extend the script to do the following:

Create an updated, merged dictionary, called it together_candidate_endpoints

From the table, test table, only exclude the dead endpoints, ok and no content status is fine.

To be clear, the object is to merger and update and not replace. No duplicates

Neatly, clean

"""
