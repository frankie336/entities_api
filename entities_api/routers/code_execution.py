import os
import subprocess
import shutil
import tempfile  # Added missing import
from fastapi import APIRouter, HTTPException  # Changed FastAPI to APIRouter
from pydantic import BaseModel

router = APIRouter()  # Changed from app = FastAPI() to router = APIRouter()


class CodeExecutionRequest(BaseModel):
    code: str
    language: str
    user_id: str


@router.post("/execute_code")  # Updated decorator to use router
def execute_code(request: CodeExecutionRequest):
    if request.language.lower() != 'python':
        raise HTTPException(status_code=400, detail="Unsupported language. Only Python is supported.")

    temp_dir = tempfile.mkdtemp(prefix=f"sandbox_{request.user_id}_")

    try:
        code_file_path = os.path.join(temp_dir, 'script.py')
        with open(code_file_path, 'w') as code_file:
            code_file.write(request.code)

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

        result = subprocess.run(
            firejail_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            # No need to set cwd since we're using full path
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
