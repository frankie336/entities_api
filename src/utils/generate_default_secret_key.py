import os
import base64


def generate_default_secret_key(length: int = 32) -> str:
    """
    Generate a default secret key for signing purposes.

    The key is generated using os.urandom for cryptographic randomness,
    then encoded in URL-safe base64 format with padding stripped.

    Args:
        length (int): Number of random bytes to generate. Default is 32.

    Returns:
        str: The generated secret key.
    """
    random_bytes = os.urandom(length)
    secret_key = base64.urlsafe_b64encode(random_bytes).decode("utf-8").rstrip("=")
    return secret_key


# Example usage:
if __name__ == "__main__":
    DEFAULT_SECRET_KEY = generate_default_secret_key()
    print("Generated DEFAULT_SECRET_KEY:", DEFAULT_SECRET_KEY)
