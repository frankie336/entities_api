# entities_api/routers/__init__.py

from fastapi import APIRouter
from .routers import router as main_router


# Create a central API router
api_router = APIRouter()

# Include all routers here without prefixes
api_router.include_router(main_router, tags=["Main API"])
