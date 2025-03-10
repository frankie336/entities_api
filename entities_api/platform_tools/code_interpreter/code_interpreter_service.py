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
        Enhanced code normalization with indentation correction and line continuation handling
        """
        # Phase 1: Basic sanitization
        replacements = {
            '“': '"', '”': '"', '‘': "'", '’': "'",
            '\u00b2': '**2', '^': '**',
            '⇒': '->',  # Unicode arrow to Python return type annotation
            '×': '*', '÷': '/',
        }
        for k, v in replacements.items():
            code = code.replace(k, v)

        # Remove non-ASCII characters except comments
        code = re.sub(r'[^\x00-\x7F]+', '', code)

        # Phase 2: Line continuation and indentation repair
        lines = []
        pending_continuation = False
        indent_size = 4  # Default Python indent

        for line in code.split('\n'):
            # Strip trailing whitespace and normalize line endings
            line = line.rstrip()

            # Detect broken line continuations
            continuation_operators = r'[+\-*/%=<>^|&@,{([:]\s*$'
            if re.search(continuation_operators, line):
                line = line.rstrip('\\').rstrip() + ' '
                pending_continuation = True
                lines.append(line)
                continue

            if pending_continuation:
                # Merge with previous line
                if lines:
                    lines[-1] += line.lstrip()
                else:
                    lines.append(line)
                pending_continuation = False
            else:
                lines.append(line)

        # Phase 3: Indentation correction
        code = []
        indent_level = 0
        for line in lines:
            line = line.expandtabs(4)

            # Strip empty lines
            if not line.strip():
                continue

            # Calculate current indentation
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)

            # Align to expected indent level
            expected_indent = indent_level * indent_size
            if current_indent < expected_indent:
                # Add missing indentation
                line = ' ' * expected_indent + stripped
            elif current_indent > expected_indent:
                # Reset to previous indent level
                line = ' ' * expected_indent + stripped

            # Update indent level
            if stripped.endswith(':'):
                indent_level += 1
            elif stripped.startswith(('return', 'pass', 'raise', 'break', 'continue')):
                indent_level = max(0, indent_level - 1)

            code.append(line)

        normalized_code = '\n'.join(code)

        # Phase 4: Wrap single expressions in print
        if re.match(r'^[\w\.]+\s*\(.*\)\s*$', normalized_code.strip()):
            normalized_code = f"print({normalized_code.strip()})"

        return self.required_imports + normalized_code



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



