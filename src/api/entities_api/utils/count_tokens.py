from transformers import AutoTokenizer

def count_tokens(input_string: str, tokenizer_name: str = "gpt2") -> int:
    """
    Count the number of tokens in the input string using a Hugging Face tokenizer.

    Args:
        input_string (str): The input string to tokenize.
        tokenizer_name (str): The name or identifier of the tokenizer to load from Hugging Face's model hub.

    Returns:
        int: The number of tokens in the input string.

    Raises:
        Exception: If the tokenizer fails to load or tokenize the input.
    """
    try:
        # Dynamically load the tokenizer from Hugging Face's model hub
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)

        # Tokenize the input string
        tokens = tokenizer.encode(input_string, add_special_tokens=False)

        # Return the number of tokens
        return len(tokens)
    except Exception as e:
        raise Exception(f"Failed to load or use the tokenizer '{tokenizer_name}': {str(e)}")


# Example usage
if __name__ == "__main__":
    input_text = "This is an example string to test tokenization."
    tokenizer_name = "bert-base-uncased"  # Replace with the desired tokenizer name

    try:
        token_count = count_tokens(input_text, tokenizer_name)
        print(f"Number of tokens: {token_count}")
    except Exception as e:
        print(f"Error: {str(e)}")
