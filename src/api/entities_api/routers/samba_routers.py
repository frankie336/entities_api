# src/api/entities_api/routers/samba_routers.py
from fastapi import APIRouter

from entities_api.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()


