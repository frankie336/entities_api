from entities_api.inference.inference_arbiter import InferenceArbiter


class InferenceProviderSelector:
    """
    Selects the appropriate inference provider instance from an InferenceArbiter
    based on given parameters such as provider and model.
    """

    def __init__(self, arbiter: InferenceArbiter):
        self.arbiter = arbiter

    def select_provider(self, provider: str, model: str):
        """
        Select and return the appropriate inference provider instance.

        Args:
            provider (str): The name of the inference provider (e.g., "deepseek", "groq", "azure", "hyperbolic", "together", "local").
            model (str): The model identifier or version (e.g., "r1", "v3", or a longer identifier for hyperbolic).

        Returns:
            An instance of the selected inference provider.

        Raises:
            ValueError: If the provider and model combination is invalid.
        """
        provider = provider.lower().strip()
        model = model.lower().strip()

        # Dictionary mapping provider names to another dictionary that maps models
        # to the corresponding arbiter methods (notably, using lambdas or direct references).
        mapper = {
            "deepseek": {
                "r1": self.arbiter.get_deepseek_r1,
                "v3": self.arbiter.get_deepseek_v3,
            },
            "groq": {
                "default": self.arbiter.get_groq,
            },
            "azure": {
                "default": self.arbiter.get_azure_r1,
            },

            "hyperbolic": {
                "hyperbolic/deepseek-ai/deepseek-r1": self.arbiter.get_hyperbolic_r1,
                "hyperbolic/deepseek-ai/deepseek-v3": self.arbiter.get_hyperbolic_v3,
                "hyperbolic/meta-llama/llama-3.3-70b-instruct": self.arbiter.get_hyperbolic_llama3,


            },
            "togetherai": {
                "r1": self.arbiter.get_together_r1,
                "v3": self.arbiter.get_together_v3,
                "together-ai/meta-llama/llama-2-70b-hf": self.arbiter.get_together_llama2,
            },


            "local": {
                "default": self.arbiter.get_local,
            },
        }

        if provider not in mapper:
            raise ValueError(f"Invalid provider: '{provider}'")

        provider_map = mapper[provider]
        # First try to find an exact match for the model.
        if model in provider_map:
            return provider_map[model]()
        # Else, if a default value is provided for this provider, use that.
        elif "default" in provider_map:
            return provider_map["default"]()
        else:
            raise ValueError(f"Invalid model '{model}' for provider '{provider}'")
