# entities_api/routers/code_execution.py
import os

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from entities_api.clients.client_code_executor import ClientCodeService
from entities_api.services.code_executor_service import CodeExecutorService
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()
router = APIRouter()

# Models for request and response
class CodeExecutionRequest(BaseModel):
    code: str
    language: str
    user_id: str

class CodeExecutionResponse(BaseModel):
    output: Optional[str] = None
    error: Optional[str] = None

# Dependency injection for code execution strategies
def get_code_executor():
    return CodeExecutorService()

def get_sandbox_client():
    sandbox_url = os.getenv("SANDBOX_SERVER_URL", "http://sandbox_server:8000")
    return ClientCodeService(sandbox_server_url=sandbox_url)

@router.post("/execute_code", response_model=CodeExecutionResponse)
def execute_code(
    request: CodeExecutionRequest,
    executor: CodeExecutorService = Depends(get_code_executor),
    sandbox_client: ClientCodeService = Depends(get_sandbox_client)
):
    if request.language.lower() != 'python':
        raise HTTPException(status_code=400, detail="Unsupported language. Only Python is supported.")

    logging_utility.info(f"Received code execution request from user: {request.user_id}")

    use_external_sandbox = os.getenv("USE_EXTERNAL_SANDBOX", "false").lower() == "true"
    if use_external_sandbox:
        logging_utility.info(f"Delegating code execution to external sandbox for user: {request.user_id}")
        result = sandbox_client.execute_code(request.code, request.language, request.user_id)
    else:
        logging_utility.info(f"Executing code internally using firejail for user: {request.user_id}")
        result = executor.execute_python_code(request.code, request.user_id)

    if 'error' in result:
        logging_utility.error(f"Code execution error: {result['error']}")
        raise HTTPException(status_code=400, detail=result['error'])
    else:
        logging_utility.info("Code executed successfully.")
        return CodeExecutionResponse(output=result['output'])
