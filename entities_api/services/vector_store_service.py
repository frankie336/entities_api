import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
from pathlib import Path
from typing import List, Dict, Optional, Union

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, joinedload
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type

from entities_api.interfaces.base_vector_store import StoreNotFoundError, VectorStoreError
from entities_api.models.models import VectorStore, Base, Assistant
from entities_api.schemas import StatusEnum, VectorStoreRead, VectorStoreSearchResult, ProcessOutput
from entities_api.services.file_processor import FileProcessor
from entities_api.services.identifier_service import IdentifierService
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.vector_store_manager import VectorStoreManager
from entities_api.schemas import VectorStoreCreate
logging_utility = LoggingUtility()


class VectorStoreService:
    def __init__(self):
        # Create a local engine for all DB operations.
        DATABASE_URL = "mysql+pymysql://ollama:3e4Qv5uo2Cg31zC1@localhost:3307/cosmic_catalyst"


        self.engine = create_engine(DATABASE_URL, echo=True)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.vector_manager = VectorStoreManager()
        self.identity_service = IdentifierService()
        self.file_processor = FileProcessor()
        self._batch_executor = ThreadPoolExecutor(max_workers=4)
        self.file_processor = FileProcessor()

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential())
    def create_vector_store(self, name: str, user_id: str) -> VectorStoreRead:
        """Create store with improved error handling."""
        payload = VectorStoreCreate(
            name=name,
            user_id=user_id,
            vector_size=384,
            distance_metric="COSINE",
            config={"example": "value"}
        )
        unique_id = self.identity_service.generate_vector_id()
        try:
            response = self.vector_manager.create_store(
                store_name=unique_id,
                vector_size=payload.vector_size,
                distance=payload.distance_metric
            )
            logging_utility.debug(f"Qdrant response: {response}")

            # Use a fresh session for DB operations
            with self.SessionLocal() as session:
                with session.begin():
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
                    session.add(new_vector_store)
                session.refresh(new_vector_store)

            # Pydantic V2: use model_validate instead of from_orm
            return VectorStoreRead.model_validate(new_vector_store)
        except Exception as e:
            logging_utility.error(f"Create store failed: {str(e)}")
            self.vector_manager.delete_store(unique_id)
            raise

    def add_to_store(self, store_name: str, texts: List[str],
                     vectors: List[List[float]], metadata: List[dict]) -> dict:
        """Batch insert with improved error logging."""
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(min=1, max=10),
        retry=retry_if_exception_type(VectorStoreError),
        retry_error_callback=lambda state: state.outcome.result()
    )

    def search_vector_store(
            self,
            store_name: str,
            query_text: str,
            top_k: int = 5,
            filters: Optional[Dict] = None,
            score_threshold: float = 0.5
    ) -> List[VectorStoreSearchResult]:


        """
        Semantic search with hybrid filtering.
        - query_text: Natural language query
        - top_k: Number of results to return
        - filters: Key-value filters for metadata
        - score_threshold: Minimum relevance score (0-1)
        """
        try:
            with self.SessionLocal() as session:
                store = session.query(VectorStore).filter(
                    VectorStore.collection_name == store_name,
                    VectorStore.status == StatusEnum.active
                ).first()
            if not store:
                raise StoreNotFoundError(f"Vector store {store_name} not found")
            query_vector = self.file_processor.embedding_model.encode(
                [query_text],
                convert_to_numpy=True
            ).tolist()[0]
            raw_results = self.vector_manager.query_store(
                store_name=store_name,
                query_vector=query_vector,
                top_k=top_k,
                filters=filters
            )
            processed_results = []
            for result in raw_results:
                if result['score'] >= score_threshold:
                    processed_results.append(VectorStoreSearchResult(
                        text=result['text'],
                        metadata=result.get('metadata', {}),
                        score=result['score'],
                        vector_id=str(result['id']),
                        store_id=store.id
                    ))
            return processed_results
        except Exception as e:
            logging_utility.error(f"Search failed: {str(e)}")
            raise VectorStoreError(f"Search operation failed: {str(e)}")

    def batch_search(
            self,
            queries: List[str],
            store_name: str,
            top_k: int = 5,
            filters: Optional[Dict] = None
    ) -> Dict[str, List[VectorStoreSearchResult]]:
        """
        Process multiple searches in parallel.
        - queries: List of search queries
        - store_name: Vector store to search
        - top_k: Number of results per query
        - filters: Metadata filters to apply to all queries
        Returns: Dictionary mapping each query to its results
        """
        try:
            with self.SessionLocal() as session:
                store = session.query(VectorStore).filter(
                    VectorStore.collection_name == store_name,
                    VectorStore.status == StatusEnum.active
                ).first()
            if not store:
                raise StoreNotFoundError(f"Vector store {store_name} not found")
            with self._batch_executor as executor:
                futures = {
                    query: executor.submit(
                        self.search_vector_store,
                        store_name,
                        query,
                        top_k,
                        filters
                    )
                    for query in queries
                }
                return {
                    query: future.result()
                    for query, future in futures.items()
                }
        except Exception as e:
            logging_utility.error(f"Batch search failed: {str(e)}")
            raise VectorStoreError(f"Batch search operation failed: {str(e)}")

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=1, max=5))
    def delete_vector_store(self, store_name: str, permanent: bool = False) -> dict:
        """
        Delete a vector store and its associated data.
        - permanent: If True, physically removes all data. If False, marks as deleted (soft delete)
        """
        try:
            with self.SessionLocal() as session:
                store = session.query(VectorStore).filter(
                    VectorStore.collection_name == store_name
                ).first()
                if not store:
                    raise StoreNotFoundError(f"Vector store {store_name} not found")
                delete_result = self.vector_manager.delete_store(store_name)
                if permanent:
                    session.delete(store)
                else:
                    store.status = StatusEnum.deleted
                    store.updated_at = int(time.time())
                    session.commit()
                logging_utility.info(f"Deleted store '{store_name}', permanent={permanent}")
                return {
                    "store_name": store_name,
                    "status": "deleted",
                    "permanent": permanent,
                    "qdrant_result": delete_result
                }
        except Exception as e:
            logging_utility.error(f"Delete failed for '{store_name}': {str(e)}")
            raise VectorStoreError(f"Store deletion failed: {str(e)}")

    def list_store_files(self, store_name: str) -> List[str]:
        """Get unique source files from a vector store."""
        try:
            with self.SessionLocal() as session:
                store = session.query(VectorStore).filter(
                    VectorStore.collection_name == store_name,
                    VectorStore.status == StatusEnum.active
                ).first()
            if not store:
                raise StoreNotFoundError(f"Vector store {store_name} not found")
            return self.vector_manager.list_store_files(store_name)
        except Exception as e:
            logging_utility.error(f"File listing failed: {str(e)}")
            raise VectorStoreError(f"File listing operation failed: {str(e)}")

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=1, max=5))
    def delete_file_from_store(self, store_name: str, file_path: str) -> dict:
        """Remove all chunks of a specific file from vector store."""
        try:
            with self.SessionLocal() as session:
                store = session.query(VectorStore).filter(
                    VectorStore.collection_name == store_name,
                    VectorStore.status == StatusEnum.active
                ).first()
            if not store:
                raise StoreNotFoundError(f"Vector store {store_name} not found")
            result = self.vector_manager.delete_file_from_store(store_name, file_path)
            with self.SessionLocal() as session:
                store = session.query(VectorStore).filter(
                    VectorStore.collection_name == store_name
                ).first()
                try:
                    store.file_count = max(0, store.file_count - 1)
                    store.updated_at = int(time.time())
                    session.commit()
                except Exception as db_error:
                    session.rollback()
                    raise VectorStoreError(f"Database update failed: {str(db_error)}")
            logging_utility.info(f"Deleted file '{file_path}' from store '{store_name}'")
            return result
        except Exception as e:
            logging_utility.error(f"File deletion failed: {str(e)}")
            raise VectorStoreError(f"File deletion operation failed: {str(e)}")

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=1, max=5))
    def add_files(self, file_path: Union[str, Path], destination_store: str,
                  vector_service, user_metadata: dict = None, source_url: str = None) -> dict:

        vector_service = VectorStoreService()
        result = self.file_processor.process_and_store(file_path=file_path,
                                                       destination_store=destination_store,
                                                       vector_service=vector_service,
                                                       user_metadata=user_metadata

                                                       )


        # Convert the dictionary to a Pydantic object before returning.
        return ProcessOutput(**result)

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=1, max=5))
    def attach_vector_store_to_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        with self.SessionLocal() as session:
            # Load both objects in the same session
            vector_store = session.get(VectorStore, vector_store_id)
            assistant = session.get(Assistant, assistant_id)

            if not vector_store:
                logging_utility.warning("Vector store with ID %s not found.", vector_store_id)
                raise HTTPException(status_code=404, detail=f"Vector store with id {vector_store_id} not found")
            if not assistant:
                logging_utility.warning("Assistant with ID %s not found.", assistant_id)
                raise HTTPException(status_code=404, detail=f"Assistant with id {assistant_id} not found")

            # Append and commit in the same session
            assistant.vector_stores.append(vector_store)
            session.commit()
            logging_utility.info("Successfully associated vector store ID %s with assistant ID %s", vector_store_id,
                                 assistant_id)
            return True

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=1, max=5))
    def detach_vector_store_from_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        with self.SessionLocal() as session:
            # Load both objects in the same session
            assistant = session.get(Assistant, assistant_id)
            vector_store = session.get(VectorStore, vector_store_id)

            if not assistant:
                logging_utility.warning("Assistant with ID %s not found.", assistant_id)
                raise HTTPException(status_code=404, detail=f"Assistant with id {assistant_id} not found")
            if not vector_store:
                logging_utility.warning("Vector store with ID %s not found.", vector_store_id)
                raise HTTPException(status_code=404, detail=f"Vector store with id {vector_store_id} not found")

            # Ensure the vector store is actually linked to the assistant
            if vector_store not in assistant.vector_stores:
                logging_utility.info("Vector store ID %s is not attached to assistant ID %s", vector_store_id,
                                     assistant_id)
                return False  # Nothing was changed

            # Remove the vector store from the assistant
            assistant.vector_stores.remove(vector_store)
            session.commit()
            logging_utility.info("Successfully detached vector store ID %s from assistant ID %s", vector_store_id,
                                 assistant_id)
            return True


    def get_vector_stores_for_assistant(self, assistant_id: str) -> List[VectorStoreRead]:
        """
        Retrieve all vector stores associated with a given assistant.
        """
        with self.SessionLocal() as session:
            # Eagerly load the vector_stores relationship.
            assistant = session.query(Assistant).options(
                joinedload(Assistant.vector_stores)
            ).filter(Assistant.id == assistant_id).first()

            if not assistant:
                raise HTTPException(status_code=404, detail="Assistant not found")

            # Convert each VectorStore ORM object into a Pydantic model.
            return [VectorStoreRead.model_validate(vs) for vs in assistant.vector_stores]



# ==============================
# Test the workflow in the main block
# ==============================
if __name__ == "__main__":
    logging_utility = LoggingUtility()

    # Since the service creates its own engine, just instantiate it.
    vector_service = VectorStoreService()
    test_file_path = Path("test_file.txt")

    # Create a test payload using VectorStoreCreate (for reference)
    from entities_api.schemas import VectorStoreCreate

    test_payload = VectorStoreCreate(
        name="Test_Vector_Store",
        user_id="test_user",
        vector_size=384,
        distance_metric="COSINE",
        config={"example": "value"}
    )

    try:
        # Create the vector store
        created_store = vector_service.create_vector_store(test_payload.name, test_payload.user_id)
        print(f"Created Vector Store: {created_store}")

        # Create a test file
        test_file_path.write_text("This is a test document for the vector store.", encoding="utf-8")
        print(f"Created test file at: {test_file_path}")

        # Process the file and add to the store using the file processor
        file_processor = FileProcessor()
        response = file_processor.process_and_store(test_file_path, created_store.collection_name, vector_service)
        print(f"File processed successfully: {response}")

        # Verify store content (using the vector manager directly)
        store_info = vector_service.vector_manager.get_store_info(created_store.collection_name)
        print(f"Store info: {store_info}")

        # Perform a search

        search_query = "test document"
        print(f"\nSearching store for: '{search_query}'")
        search_results = vector_service.search_vector_store(
            store_name=created_store.collection_name,
            query_text=search_query,
            top_k=3,
            score_threshold=0.3
        )



        if search_results:
            print("\nSearch Results:")
            for i, result in enumerate(search_results, 1):
                print(f"\nResult {i}:")
                print(f"  Text: {result.text}")
                print(f"  Score: {result.score:.3f}")
                print(f"  Metadata: {result.metadata}")
        else:
            print("No results found matching the query.")

        # List store files
        print("\nFiles in store:")
        files = vector_service.list_store_files(created_store.collection_name)
        print(f"Stored files: {files}")


        # Test file deletion
        print("\nTesting file deletion...")
        delete_result = vector_service.delete_file_from_store(
            store_name=created_store.collection_name,
            file_path=str(test_file_path)
        )
        print(f"Deletion result: {delete_result}")
        print("Remaining files:")
        print(vector_service.list_store_files(created_store.collection_name))

        # Test store deletion
        print("\nTesting store deletion...")
        delete_result = vector_service.delete_vector_store(created_store.collection_name)
        print(f"Deletion result: {delete_result}")
        try:
            vector_service.search_vector_store(created_store.collection_name, "test")
        except StoreNotFoundError:
            print("Store successfully deleted")

    except Exception as e:
        logging_utility.error(f"Main process error: {str(e)}")
        print(f"Error: {str(e)}")
    finally:
        # Cleanup: remove the test file if it exists.
        if test_file_path.exists():
            test_file_path.unlink()
