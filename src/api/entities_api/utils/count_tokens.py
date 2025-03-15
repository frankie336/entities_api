from transformers import AutoTokenizer
import os

#from entities_api.constants import ASSISTANT_INSTRUCTIONS

tokenizer_path = r"\USERS\FRANC\MODELS\HUGGINGFACE\DEEPSEEK-R1-DISTILL-QWEN-1.5B"  # Path to your local tokenizer

def count_tokens(input_string: str, tokenizer_path: str =tokenizer_path) -> int:
    """
    Count the number of token_count in the input string using the local tokenizer.

    Args:
        input_string (str): The input string to tokenize.
        tokenizer_path (str): The path to the local tokenizer directory.

    Returns:
        int: The number of token_count in the input string.

    Raises:
        FileNotFoundError: If the tokenizer path does not exist.
        Exception: If the tokenizer fails to load.
    """
    tokenizer_path = r"\USERS\FRANC\MODELS\HUGGINGFACE\DEEPSEEK-R1-DISTILL-QWEN-1.5B"

    # Check if the tokenizer path exists
    if not os.path.exists(tokenizer_path):
        raise FileNotFoundError(f"Tokenizer path '{tokenizer_path}' does not exist.")

    try:
        # Load the tokenizer from the local path
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)

        # Tokenize the input string
        tokens = tokenizer.encode(input_string, add_special_tokens=False)

        # Return the number of token_count
        return len(tokens)
    except Exception as e:
        raise Exception(f"Failed to load tokenizer: {str(e)}")


# Example usage
if __name__ == "__main__":
    #input_text = BASE_ASSISTANT_INSTRUCTIONS
    input_text = markdown_dict["markdown"]
    try:
        token_count = count_tokens(input_text, tokenizer_path)
        print(f"Number of token_count: {token_count}")
    except Exception as e:
        print(f"Error: {str(e)}")