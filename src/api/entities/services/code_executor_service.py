import os
import subprocess
import shutil
import tempfile
from typing import Dict, Any
from entities.services.logging_service import LoggingUtility

# Initialize the logging utility
logging_utility = LoggingUtility()


class CodeExecutorService:
    def __init__(self):
        logging_utility.info("CodeExecutorService initialized")

    def execute_python_code(self, code: str, user_id='test_user') -> Dict[str, Any]:
        """
        Executes Python code in a sandboxed environment using Firejail.

        Args:
            code (str): The Python code to execute.
            user_id (str): The ID of the user executing the code.

        Returns:
            Dict[str, Any]: A dictionary containing the original code, output, or error.
        """
        temp_dir = tempfile.mkdtemp(prefix=f"sandbox_{user_id}_")
        logging_utility.info("Created temporary directory: %s for user: %s", temp_dir, user_id)

        try:
            # Write code to a file in the temporary directory
            code_file_path = os.path.join(temp_dir, 'script.py')
            with open(code_file_path, 'w') as code_file:
                code_file.write(code)
            logging_utility.info("Wrote code to %s for user: %s", code_file_path, user_id)

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
            logging_utility.info("Executing command: %s for user: %s", ' '.join(firejail_command), user_id)

            # Execute the command
            result = subprocess.run(
                firejail_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            # Capture output and errors
            output = result.stdout.decode().strip()
            errors = result.stderr.decode().strip()
            exit_code = result.returncode

            if exit_code != 0:
                logging_utility.error(
                    "Execution failed with exit code %s for user: %s, Error: %s",
                    exit_code, user_id, errors
                )
                return {'code': code, 'error': errors}
            else:
                logging_utility.info(
                    "Execution completed successfully for user: %s, Output: %s",
                    user_id, output
                )
                return {'code': code, 'output': output}

        except subprocess.TimeoutExpired:
            logging_utility.error("Execution timed out for user: %s", user_id)
            return {'code': code, 'error': 'Execution timed out.'}
        except Exception as e:
            logging_utility.exception(
                "An unexpected error occurred during execution for user: %s",
                user_id
            )
            return {'code': code, 'error': 'An unexpected error occurred.'}
        finally:
            try:
                shutil.rmtree(temp_dir)
                logging_utility.info("Removed temporary directory: %s for user: %s", temp_dir, user_id)
            except Exception as cleanup_error:
                logging_utility.error(
                    "Failed to remove temporary directory: %s for user: %s, Error: %s",
                    temp_dir, user_id, str(cleanup_error)
                )
