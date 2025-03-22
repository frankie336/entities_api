# entities/routers/__init__.py

from fastapi import APIRouter
from .routers import router as main_router
from .handler_routers import router as handler_router
from .inference_routers import router as inference_router
from  .samba_routers import router as samba_router

# Create a central API router
api_router = APIRouter()

# Include all routers here without prefixes
api_router.include_router(main_router, tags=["Main API"])
api_router.include_router(handler_router, tags=["event_handler"])
api_router.include_router(inference_router, tags=["inference"])
api_router.include_router(samba_router, tags=["samba"])

