# entities_api/routers/__init__.py

from fastapi import APIRouter
from .code_execution import router as code_execution_router
from .routers import router as main_router  # Import main router for user, threads, tools, etc.

# Create a central API router
api_router = APIRouter()

# Include all routers here without prefixes
api_router.include_router(code_execution_router, tags=["Code Execution"])
api_router.include_router(main_router, tags=["Main API"])
