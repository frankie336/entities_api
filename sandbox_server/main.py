# sandbox_server/main.py

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import tempfile
import shutil
import os

app = FastAPI()

class CodeExecutionRequest(BaseModel):
    code: str
    language: str
    user_id: str

@app.post("/execute_code")
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
            f'--private={temp_dir}',
            '--net=none',
            '--cpu=1',
            '--seccomp',
            '--rlimit-as=128M',
            'python', 'script.py'
        ]

        result = subprocess.run(
            firejail_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
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
