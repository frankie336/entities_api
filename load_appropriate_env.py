import os
from dotenv import load_dotenv


def load_appropriate_env():
    """
    Load environment variables from the correct .env file.

    If RUNNING_IN_CONTAINER is set to "True", this function loads environment
    variables from '.env.container'. Otherwise, it loads them from '.env.local'.
    """
    # Determine which .env file to load
    env_file = ".env.container" if os.environ.get("RUNNING_IN_CONTAINER", "False") == "True" else ".env.local"

    # Load the environment variables from the selected file
    load_dotenv(dotenv_path=env_file)

    # Log or print which file was loaded
    print(f"Loaded environment variables from {env_file}")
