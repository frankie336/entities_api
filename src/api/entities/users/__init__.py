# entities/routers/__init__.py

from fastapi import APIRouter
from .routers import router as main_router
from .handlers import router as handlers
from .inference import router as inference
from  .samba import router as samba
from  .threads import router as threads

# Create a central API router
api_router = APIRouter()

# Include all routers here without prefixes
api_router.include_router(main_router, tags=["Main API"])
api_router.include_router(handlers, tags=["event_handler"])
api_router.include_router(inference, tags=["inference"])
api_router.include_router(samba, tags=["samba"])
api_router.include_router(threads, tags=["samba"])
