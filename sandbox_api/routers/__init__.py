# entities_api/routers/__init__.py
from fastapi import APIRouter
from .ws_router import router as ws_router
# Create a central API router
api_router = APIRouter()
api_router.include_router(ws_router, tags=["Web Socket"])