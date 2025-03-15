# entities_api/routers.py
from fastapi import APIRouter

from src.entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()
router = APIRouter()


