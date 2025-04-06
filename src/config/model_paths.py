import os


def get_model_path(model_name: str, use_docker: bool = False) -> str:
    """
    Return the absolute path for a given model name based on our naming convention.
    If use_docker is True, the model path will be set for Docker environments.
    """
    if use_docker:
        # Path for Docker environment
        base_dir = "/app/models"
    else:
        # Default path for local environment
        base_dir = os.path.join("C:", os.sep, "Users", "franc", "Models", "HuggingFace")

    model_mapping = {
        "ri-qwen2.5-math-1.5b": "DeepSeek-R1-Distill-Qwen-1.5B",
        "ri-qwen2.5-math-7b": "DeepSeek-R1-Distill-Qwen-7B",
        "ri-llama3.1-8b": "DeepSeek-R1-Distill-Llama-8B",
        "ri-qwen2.5-14b": "DeepSeek-R1-Distill-Qwen-14B",
        "ri-qwen2.5-32b": "DeepSeek-R1-Distill-Qwen-32B",
        "ri-llama3.3-70b-instruct": "DeepSeek-R1-Distill-Llama-70B",
    }

    key = model_name.lower()
    if key not in model_mapping:
        raise ValueError(
            f"Model name '{model_name}' is not recognized. Available models: {list(model_mapping.keys())}"
        )

    return os.path.join(base_dir, model_mapping[key])
