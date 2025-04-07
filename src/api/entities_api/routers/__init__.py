# entities_api/routers/__init__.py

from fastapi import APIRouter

# Import routers with a clear suffix alias
from .routers import router as main_router
from .events import router as events_router
from .inference import router as inference_router
from .samba import router as samba_router
from .threads import router as threads_router
from .users import router as users_router
from .messages import router as messages_router
from .runs import router as runs_router
from .assistants import router as assistants_router
from .tools import router as tools_router
from .actions import router as actions_router
from .files import router as files_router
from .vectors import router as vectors_router

# Create a central API router
api_router = APIRouter()

api_router.include_router(main_router, tags=["Main API"])
api_router.include_router(events_router, tags=["Event Monitoring"])
api_router.include_router(inference_router, tags=["Inference"])
api_router.include_router(samba_router, tags=["Samba"])
api_router.include_router(threads_router, tags=["Threads"])
api_router.include_router(users_router, tags=["Users"])
api_router.include_router(runs_router, tags=["Runs"])
api_router.include_router(assistants_router, tags=["Assistants"])
api_router.include_router(messages_router, tags=["Messages"])
api_router.include_router(tools_router, tags=["Tools"])
api_router.include_router(actions_router, tags=["Actions"])
api_router.include_router(files_router, tags=["Files"])
api_router.include_router(vectors_router, tags=["Vector Stores"])
