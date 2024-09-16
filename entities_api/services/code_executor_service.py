import os
import subprocess
import shutil
import tempfile
from typing import Dict, Any
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class CodeExecutorService:
    def __init__(self):
        logging_utility.info("CodeExecutorService initialized")

    def execute_python_code(self, code: str, user_id: str) -> Dict[str, Any]:
        """
        Executes Python code in a sandboxed environment using Firejail.

        Args:
            code (str): The Python code to execute.
            user_id (str): The ID of the user executing the code.

        Returns:
            Dict[str, Any]: A dictionary containing the original code, output, or error.
        """
        temp_dir = tempfile.mkdtemp(prefix=f"sandbox_{user_id}_")
        logging_utility.info(f"Created temporary directory: {temp_dir} for user: {user_id}")

        try:
            # Write code to a file in the temporary directory
            code_file_path = os.path.join(temp_dir, 'script.py')
            with open(code_file_path, 'w') as code_file:
                code_file.write(code)
            logging_utility.info(f"Wrote code to {code_file_path} for user: {user_id}")

            # Firejail command to sandbox the execution
            firejail_command = [
                'firejail',
                '--quiet',
                f'--bind={temp_dir}:{temp_dir}',
                '--net=none',
                '--cpu=1',
                '--seccomp',
                '--rlimit-as=128M',
                'python', code_file_path
            ]
            logging_utility.info(f"Executing command: {' '.join(firejail_command)} for user: {user_id}")

            # Execute the command
            result = subprocess.run(
                firejail_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            # Capture output and errors
            output = result.stdout.decode()
            errors = result.stderr.decode()
            exit_code = result.returncode

            if exit_code != 0:
                logging_utility.error(f"Execution failed with exit code {exit_code} for user: {user_id}, Error: {errors.strip()}")
                return {'code': code, 'error': errors.strip()}
            else:
                logging_utility.info(f"Execution completed successfully for user: {user_id}, Output: {output.strip()}")
                return {'code': code, 'output': output.strip()}

        except subprocess.TimeoutExpired:
            logging_utility.error(f"Execution timed out for user: {user_id}")
            return {'code': code, 'error': 'Execution timed out.'}
        except Exception as e:
            logging_utility.error(f"An error occurred during execution for user: {user_id}, Error: {str(e)}")
            return {'code': code, 'error': str(e)}
        finally:
            shutil.rmtree(temp_dir)
            logging_utility.info(f"Removed temporary directory: {temp_dir} for user: {user_id}")
