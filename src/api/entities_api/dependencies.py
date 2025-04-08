# entities_api/dependencies.py
from sqlalchemy.orm import Session

from entities_api.db.database import SessionLocal


def get_db() -> Session:
    """Dependency to provide a database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
