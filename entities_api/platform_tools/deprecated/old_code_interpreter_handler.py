import json
import os
import re

from entities_api.clients.client_code_executor import ClientCodeService
from entities_api.services.logging_service import LoggingUtility

# Initialize the logging utility and OllamaClient
logging_utility = LoggingUtility()


def normalize_code(code: str) -> str:
    """
    Normalizes the inbound code by handling special characters, ensuring valid Python syntax,
    and sanitizing non-ASCII characters and escape sequences.

    Args:
        code (str): The code snippet to normalize.

    Returns:
        str: The normalized code.
    """
    # Replace curly quotes with straight quotes
    code = code.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")

    # Replace Unicode superscript ² with **2 for exponentiation
    code = code.replace('\u00b2', '**2')

    # Replace double backslashes with single backslashes
    code = code.replace('\\\\', '\\')

    # Normalize escaped newlines and tabs
    code = code.encode('utf-8').decode('unicode_escape')

    # Remove any remaining non-ASCII characters
    code = re.sub(r'[^\x00-\x7F]+', '', code)

    return code


def code_interpreter(code: str, language: str = "python", user_id: str = "test_user") -> str:
    """
    Executes the provided code in the given language using the code_executor_service
    and returns the result or error in a structured JSON format with the keys 'result' for output
    and 'error' for any errors encountered.

    The response will include both the executed code and the output/error.

    Args:
        code (str): The code snippet to execute.
        language (str): The programming language of the code (default is "python").
        user_id (str): The user ID requesting the code execution. Defaults to 'test_user' if not provided.

    Returns:
        str: A JSON-formatted string with either 'result' for successful execution or 'error' if something went wrong.
             The 'result' key will contain the executed code and the corresponding output.
    """

    # Ensure user_id is valid, fallback to 'test_user' if invalid
    if not user_id:
        logging_utility.warning("User ID is null or invalid. Falling back to 'test_user'.")
        user_id = "test_user"

    logging_utility.info("Normalizing code for user: %s", user_id)

    # Normalize the inbound code to handle potential formatting issues
    normalized_code = normalize_code(code)

    logging_utility.info("Executing code for user: %s", user_id)

    try:

        # Execute the code using the OllamaClient's code_executor_service

        client = ClientCodeService(
            sandbox_server_url=os.getenv('CODE_SERVER_URL', 'http://localhost:9000/v1/execute_code')
        )

        response = client.execute_code(code=normalized_code, language=language, user_id=user_id)


        # Check if there was an error
        if response.get('error'):
            logging_utility.error("Code execution error: %s", response['error'])
            return json.dumps({
                "error": {
                    "code": normalized_code,
                    "message": response['error']
                }
            })

        # Otherwise, return the output along with the code as part of the 'result' key
        logging_utility.info("Code executed successfully. Result: %s", response['output'])
        return json.dumps({
            "result": {
                "code": normalized_code,
                "output": response['output']
            }
        })

    except Exception as e:
        error_message = f"Error executing code: {str(e)}"
        logging_utility.error(error_message)
        return json.dumps({
            "error": {
                "code": normalized_code,
                "message": error_message
            }
        })


