import requests
from typing import Dict, Any
from entities.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class ClientCodeService:
    def __init__(self, sandbox_server_url: str):
        """
        Initializes the ClientCodeService with the given sandbox server URL.

        Args:
            sandbox_server_url (str): The base URL of the sandbox server.
        """
        # Ensure the base URL does not end with a slash
        self.sandbox_server_url = sandbox_server_url.rstrip('/')
        logging_utility.info(f"ClientCodeService initialized with sandbox server URL: {self.sandbox_server_url}")

    def execute_code(self, code: str, language: str, user_id: str) -> Dict[str, Any]:
        """
        Sends a request to the external sandbox server to execute code.

        Args:
            code (str): The code to execute.
            language (str): The programming language of the code.
            user_id (str): The ID of the user executing the code.

        Returns:
            Dict[str, Any]: The response from the sandbox server, including the original code.
        """
        endpoint = f"{self.sandbox_server_url}"
        payload = {
            "code": code,
            "language": language,
            "user_id": user_id
        }

        logging_utility.info(f"Sending code execution request to {endpoint} for user: {user_id}, Language: {language}")
        try:
            response = requests.post(endpoint, json=payload, timeout=10)
            response.raise_for_status()  # Ensure we catch any HTTP errors
            result = response.json()

            # Add the original code to the response
            result['code'] = code
            logging_utility.info(f"Code executed successfully for user: {user_id}. Response: {result}")
            return result
        except requests.exceptions.Timeout:
            logging_utility.error(f"Code execution timed out for user: {user_id}")
            return {"code": code, "error": "Sandbox server timed out."}
        except requests.exceptions.RequestException as e:
            logging_utility.error(f"Error during code execution for user: {user_id}, Error: {str(e)}")
            return {"code": code, "error": f"Sandbox server error: {str(e)}"}
