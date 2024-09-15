# entities_api/routers/__init__.py

from fastapi import APIRouter
from . import code_execution

api_router = APIRouter()
api_router.include_router(code_execution.router, tags=["Code Execution"])
