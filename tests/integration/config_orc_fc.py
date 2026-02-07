import dotenv

dotenv.load_dotenv()


# hyperbolic/meta-llama/Llama-3.3-70B-Instruct
# hyperbolic/deepseek-ai/DeepSeek-V3
# hyperbolic/Qwen/Qwen3-235B-A22B
# hyperbolic/Qwen/Qwen2.5-VL-7B-Instruct
# hyperbolic/openai/gpt-oss-120b
# together-ai/deepcogito/cogito-v2-1-671b
# together-ai/ServiceNow-AI/Apriel-1.6-15b-Thinker


# together-ai/deepcogito/cogito-v2-preview-llama-109B-MoE <-- Model not available
# together-ai/deepcogito/cogito-v2-preview-llama-405B <-- model not available
# together-ai/deepcogito/cogito-v2-preview-llama-70B < -- model not available

# together-ai/deepseek-ai/DeepSeek-R1-0528-tput < -- model not available
# together-ai/deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free < -- model not available

# together-ai/google/gemma-2b-it-Ishan <---Input validation error: `inputs` tokens + `max_new_tokens` must be <= 8193

# together-ai/meta-llama/Llama-3-70b-hf < -- Not entities appropved list
# together-ai/meta-llama/Llama-3.1-405B-Instruct < -- Not in approved list
# together-ai/meta-llama/Llama-3.2-1B-Instruct < -- Not in approved list


config = {
    "together_api_key": "",
    "entities_api_key": "",
    "entities_user_id": "",
    "base_url": "http://localhost:9000",
    "url": "https://api.together.xyz/v1/chat/completions",
    "model": "together-ai/marin-community/marin-8b-instruct",
    "provider": "together",
    # "provider": "hyperbolic",
    "assistant_id": "asst_13HyDgBnZxVwh5XexYu74F",
    "test_prompt": "Please fetch me the flight times between LAX and JFK.",
}
