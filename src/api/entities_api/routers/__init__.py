# entities_api/routers/__init__.py

from fastapi import APIRouter

from .actions_router import router as actions_router
from .assistants_router import router as assistants_router
from .events_router import router as events_router
from .files_router import router as files_router
from .inference_router import router as inference_router
from .messages_router import router as messages_router
from .routers import router as main_router
from .runs_router import router as runs_router
from .samba_router import router as samba_router
from .threads_router import router as threads_router
from .tools_router import router as tools_router
from .users_router import router as users_router
from .vectors_router import router as vectors_router

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
