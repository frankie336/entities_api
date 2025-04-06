# entities_api/routers.py
from typing import Dict, Any

from fastapi import APIRouter
from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()
router = APIRouter()


@router.get("/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    A simple health check endpoint that pings the database.
    Extend with any other dependency checks as needed.
    """
    health_status = {"database": False, "status": "error"}
    try:
        # Wrap the SQL query in text() so it's an executable object.
        db.execute(text("SELECT 1"))
        health_status["database"] = True
        health_status["status"] = "healthy"
        logging_utility.info("Health check passed.")
    except Exception as e:
        logging_utility.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Database connection failed.")

    return health_status
