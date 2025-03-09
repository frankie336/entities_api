import json
import os
import re

from entities_api.clients.client_code_executor import ClientCodeService
from entities_api.services.logging_service import LoggingUtility


class CodeExecutionService:
    def __init__(self):
        self.logging_utility = LoggingUtility()
        # Prepend required imports to any code executed
        self.required_imports = (
            "import asyncio\n"
            "import math\n"
            "import time\n"
            "from datetime import datetime\n"
        )

    def normalize_code(self, code: str) -> str:
        """
        Normalize the inbound code by replacing fancy quotes, superscripts,
        escape sequences, and then prepending required imports.
        """
        code = code.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
        code = code.replace('\u00b2', '**2')
        code = code.replace('\\\\', '\\')
        code = code.encode('utf-8').decode('unicode_escape')
        code = re.sub(r'[^\x00-\x7F]+', '', code)
        # If the code looks like a single expression, wrap it in print(...)
        if re.match(r'^[\w\.]+\s*\(.*\)\s*$', code.strip()):
            code = f"print({code.strip()})"
        return self.required_imports + code

    async def execute_code(self, code: str, language: str = "python", user_id: str = "test_user") -> str:
        try:
            normalized_code = self.normalize_code(code)
            client = ClientCodeService(
                sandbox_server_url=os.getenv('CODE_SERVER_URL', 'http://localhost:9000/v1/execute_code')
            )
            response = client.execute_code(code=normalized_code, language=language, user_id=user_id)
            if response.get('error'):
                return json.dumps({
                    "error": {
                        "code": normalized_code,
                        "message": response['error']
                    }
                })
            return json.dumps({
                "result": {
                    "code": normalized_code,
                    "output": response['output']
                }
            })
        except Exception as e:
            error_message = f"Error executing code: {str(e)}"
            self.logging_utility.error(error_message)
            return json.dumps({
                "error": {
                    "code": code,
                    "message": error_message
                }
            })



