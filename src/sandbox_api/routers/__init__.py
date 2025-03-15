from fastapi import APIRouter
from .v1 import v1_router

# Create a central API router
api_router = APIRouter()

# Include versioned routers
api_router.include_router(v1_router, tags=["v1"])