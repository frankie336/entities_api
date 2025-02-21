# entities_api/services/vector_store_service.py
import uuid
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from entities_api.models.models import VectorStore as VectorStoreModel
from entities_api.services.vector_store import VectorStore as QdrantVectorStore
from entities_api.schemas import VectorStoreCreate, VectorStoreRead
from entities_api.services.identifier_service import IdentifierService
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class VectorStoreService:
    def __init__(self, db: Session, qdrant_client: QdrantVectorStore):
        self.db = db
        self.qdrant = qdrant_client
        self.identity = IdentifierService()

    def create_vector_store(self, store_data: VectorStoreCreate) -> VectorStoreRead:
        """Create a new vector store with atomic DB + Qdrant operations"""
        db_store = None
        try:
            # Generate unique identifiers
            store_id = self.identity.generate_vector_id()
            collection_name = f"vs_{uuid.uuid4().hex}"

            # Create database record
            db_store = VectorStoreModel(
                id=store_id,
                name=store_id,
                user_id=store_data.user_id,
                collection_name=collection_name,
                vector_size=store_data.vector_size,
                distance_metric=store_data.distance_metric,
                config=store_data.config
            )

            # Create Qdrant collection
            self.qdrant.create_store(
                store_name=collection_name,
                vector_size=store_data.vector_size,
                distance=store_data.distance_metric
            )

            # Commit transaction
            self.db.add(db_store)
            self.db.commit()
            self.db.refresh(db_store)

            return self._convert_to_read_model(db_store)

        except Exception as e:
            # Rollback on any error
            self.db.rollback()

            # Cleanup Qdrant if collection was created
            if db_store and db_store.collection_name:
                try:
                    self.qdrant.delete_store(db_store.collection_name)
                except Exception as cleanup_error:
                    logging_utility.error(f"Cleanup failed: {str(cleanup_error)}")

            logging_utility.error(f"Vector store creation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Vector store creation failed: {str(e)}"
            )

    def _convert_to_read_model(self, db_store: VectorStoreModel) -> VectorStoreRead:
        """Convert DB model to response schema"""
        return VectorStoreRead(
            id=db_store.id,
            name=db_store.name,
            user_id=db_store.user_id,
            collection_name=db_store.collection_name,
            vector_size=db_store.vector_size,
            distance_metric=db_store.distance_metric,
            created_at=db_store.created_at,
            status=db_store.status.value,
            config=db_store.config,
            file_count=0  # New store has no files
        )