# entities/routers/__init__.py

from fastapi import APIRouter
from .routers import router as main_router
from .events import router as handlers
from .inference import router as inference
from  .samba import router as samba
from  .threads import router as threads
from  .users import router as users
from  .messages import router as messages
from  .runs import router as runs
from  .assistants import router as assistants
from  .tools import router as tools
from  .actions import router as actions
from .files import router as files
from  .events import router as events

# Create a central API router
api_router = APIRouter()

# Include all routers here without prefixes
api_router.include_router(main_router, tags=["Main API"])
api_router.include_router(handlers, tags=["event_handler"])
api_router.include_router(inference, tags=["inference"])
api_router.include_router(samba, tags=["samba"])
api_router.include_router(threads, tags=["threads"])
api_router.include_router(users, tags=["users"])
api_router.include_router(runs, tags=["runs"])
api_router.include_router(assistants, tags=["assistants"])
api_router.include_router(messages, tags=["messages"])
api_router.include_router(tools, tags=["tools"])
api_router.include_router(actions, tags=["actions"])
api_router.include_router(files, tags=["files"])
api_router.include_router(events, tags=["Event Monitoring"])