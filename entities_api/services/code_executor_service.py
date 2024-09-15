# entities_api/services/code_executor_service.py

import os
import subprocess
import shutil
import tempfile
from typing import Dict, Any
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class CodeExecutorService:
    def __init__(self):
        pass

    def execute_python_code(self, code: str, user_id: str) -> Dict[str, Any]:
        """
        Executes Python code in a sandboxed environment using Firejail.

        Args:
            code (str): The Python code to execute.
            user_id (str): The ID of the user executing the code.

        Returns:
            Dict[str, Any]: A dictionary containing the output or error.
        """
        temp_dir = tempfile.mkdtemp(prefix=f"sandbox_{user_id}_")
        logging_utility.info(f"Created temporary directory: {temp_dir}")

        try:
            code_file_path = os.path.join(temp_dir, 'script.py')
            with open(code_file_path, 'w') as code_file:
                code_file.write(code)
            logging_utility.info(f"Wrote code to {code_file_path}")

            firejail_command = [
                'firejail',
                '--quiet',
                f'--bind={temp_dir}:{temp_dir}',
                '--net=none',
                '--cpu=1',
                '--seccomp',
                '--rlimit-as=128M',
                'python', code_file_path  # Use code_file_path directly
            ]
            logging_utility.info(f"Executing command: {' '.join(firejail_command)}")

            result = subprocess.run(
                firejail_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            output = result.stdout.decode()
            errors = result.stderr.decode()
            exit_code = result.returncode

            if exit_code != 0:
                return {'error': errors.strip()}
            else:
                return {'output': output.strip()}

        except subprocess.TimeoutExpired:
            return {'error': 'Execution timed out.'}
        except Exception as e:
            return {'error': str(e)}
        finally:
            shutil.rmtree(temp_dir)
            logging_utility.info(f"Removed temporary directory: {temp_dir}")
