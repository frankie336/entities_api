import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tenacity import retry, stop_after_attempt, wait_random_exponential

from entities_api.models.models import VectorStore, Base
from entities_api.schemas import StatusEnum, VectorStoreCreate, VectorStoreRead
from entities_api.services.file_processor import FileProcessor
from entities_api.services.identifier_service import IdentifierService
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.vector_store_manager import VectorStoreManager

logging_utility = LoggingUtility()


class VectorStoreService:
    def __init__(self, db_session):
        self.db = db_session
        self.vector_manager = VectorStoreManager()
        self.identity_service = IdentifierService()
        self.file_processor = FileProcessor()
        self._batch_executor = ThreadPoolExecutor(max_workers=4)

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential())
    def create_vector_store(self, payload: VectorStoreCreate) -> VectorStoreRead:
        """Create store with improved error handling"""
        unique_id = self.identity_service.generate_vector_id()
        try:
            response = self.vector_manager.create_store(
                store_name=unique_id,
                vector_size=payload.vector_size,
                distance=payload.distance_metric
            )
            logging_utility.debug(f"Qdrant response: {response}")

            with self.db.begin():
                new_vector_store = VectorStore(
                    id=unique_id,
                    name=payload.name,
                    user_id=payload.user_id,
                    collection_name=unique_id,
                    vector_size=payload.vector_size,
                    distance_metric=payload.distance_metric,
                    created_at=int(time.time()),
                    status=StatusEnum.active,
                    config=payload.config
                )
                self.db.add(new_vector_store)

            # Use Pydantic v2 compatible method
            return VectorStoreRead.model_validate(new_vector_store)

        except Exception as e:
            logging_utility.error(f"Create store failed: {str(e)}")
            self.vector_manager.delete_store(unique_id)
            raise

    def add_to_store(self, store_name: str, texts: List[str],
                     vectors: List[List[float]], metadata: List[dict]) -> dict:
        """Batch insert with improved error logging"""
        try:
            results = []
            for i in range(0, len(texts), 100):
                batch = {
                    "texts": texts[i:i + 100],
                    "vectors": vectors[i:i + 100],
                    "metadata": metadata[i:i + 100]
                }
                result = self.vector_manager.add_to_store(store_name, **batch)
                results.append({
                    "batch_index": len(results),
                    "items_processed": len(batch['texts']),
                    "result": result
                })
            return {"batches": results}
        except Exception as e:
            logging_utility.error(f"Batch insert failed: {str(e)}")
            raise

    def create_store_for_file_type(self, file_type):
        return self.vector_manager.create_store_for_file_type(file_type)


if __name__ == "__main__":
    from entities_api.services.logging_service import LoggingUtility

    logging_utility = LoggingUtility()

    # Database setup
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db_session = SessionLocal()

    # Test payload
    test_payload = VectorStoreCreate(
        name="Test_Vector_Store",
        user_id="test_user",
        vector_size=384,
        distance_metric="COSINE",
        config={"example": "value"}
    )

    # Service instance
    vector_service = VectorStoreService(db_session)

    try:
        # Create store
        created_store = vector_service.create_vector_store(test_payload)
        print(f"Created Vector Store: {created_store}")

        # Create test file
        test_file_path = Path("test_file.txt")
        test_file_path.write_text("This is a test document for the vector store.", encoding="utf-8")

        # Process file
        file_processor = FileProcessor()
        response = file_processor.process_and_store(test_file_path, vector_service)
        print(f"File processed successfully: {response}")

    except Exception as e:
        logging_utility.error(f"Main process error: {str(e)}")
        print(f"Error: {str(e)}")
    finally:
        # Cleanup
        if test_file_path.exists():
            test_file_path.unlink()
        db_session.close()