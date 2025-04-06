# entities_api/dependencies.py
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient
from entities_api.services.vector_store_manager import VectorStoreManager as QdrantVectorStore
from entities_api.db.database import SessionLocal  # Adjust import based on your project structure


def get_db() -> Session:
    """Dependency to provide a database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_qdrant_client() -> QdrantVectorStore:
    """Dependency to provide a Qdrant client"""
    qdrant = QdrantClient(host="localhost", port=6333)  # Adjust host/port as needed
    return QdrantVectorStore(qdrant)
