# entities_api/new_clients/client_code_executor.py

import requests
from typing import Dict, Any


class ClientCodeService:
    def __init__(self, sandbox_server_url: str):
        # Ensure the base URL does not end with a slash
        self.sandbox_server_url = sandbox_server_url.rstrip('/')

    def execute_code(self, code: str, language: str, user_id: str) -> Dict[str, Any]:
        """
        Sends a request to the external sandbox server to execute code.

        Args:
            code (str): The code to execute.
            language (str): The programming language of the code.
            user_id (str): The ID of the user executing the code.

        Returns:
            Dict[str, Any]: The response from the sandbox server.
        """
        # Correct the endpoint to avoid appending "/execute_code" multiple times
        endpoint = f"{self.sandbox_server_url}"

        payload = {
            "code": code,
            "language": language,
            "user_id": user_id
        }

        try:
            response = requests.post(endpoint, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            return {"error": "Sandbox server timed out."}
        except requests.exceptions.RequestException as e:
            return {"error": f"Sandbox server error: {str(e)}"}
