import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
from pathlib import Path
from typing import Any
from typing import List, Dict, Optional, Union

from entities_common import ValidationInterface, UtilsInterface
from qdrant_client.http import models
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, joinedload
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type
from entities.constants.platform import DIRECT_DATABASE_URL
from entities.interfaces.base_vector_store import StoreNotFoundError, VectorStoreError
from entities.models.models import VectorStore, Base, Assistant
from entities.services.file_processor import FileProcessor
from entities.services.logging_service import LoggingUtility
from entities.services.vector_store_manager import VectorStoreManager

validator = ValidationInterface()

logging_utility = LoggingUtility()


class VectorStoreService:
    def __init__(self, base_url=None, api_key=None):
        # Create a local engine for all DB operations.
        self.base_url = base_url
        self.api_key = api_key

        self.engine = create_engine(DIRECT_DATABASE_URL, echo=True)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        Base.metadata.create_all(bind=self.engine)

        self.vector_manager = VectorStoreManager()
        self.identity_service = UtilsInterface.IdentifierService()
        self.file_processor = FileProcessor()
        self._batch_executor = ThreadPoolExecutor(max_workers=4)
        self.file_processor = FileProcessor()

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential())
    def create_vector_store(self, name: str, user_id: str) ->validator.VectorStoreRead:
        """Create store with improved error handling."""
        payload = validator.VectorStoreCreate(
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
                        status=validator.StatusEnum.active.value,
                        config=payload.config
                    )
                    session.add(new_vector_store)
                session.refresh(new_vector_store)

            # Pydantic V2: use model_validate instead of from_orm
            return validator.VectorStoreRead.model_validate(new_vector_store)
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

    def _generate_cache_key(self, filters: dict) -> str:
        """Generate consistent hash-based cache key for filters"""

        def serialize(obj):
            if isinstance(obj, dict):
                return {k: serialize(v) for k, v in sorted(obj.items())}
            elif isinstance(obj, (list, tuple)):
                return [serialize(item) for item in obj]
            else:
                return str(obj)

        try:
            normalized = serialize(filters)
            serialized = json.dumps(normalized, sort_keys=True)
            return hashlib.sha256(serialized.encode()).hexdigest()[:16]
        except TypeError as e:
            logging_utility.error(f"Serialization failed: {str(e)}")
            raise ValueError("Invalid filter structure for caching")
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
            score_threshold: float = 0.5,
            page: int = 1,
            page_size: int = 10,
            score_boosts: Optional[Dict[str, float]] = None,
            explain: bool = False,
            cache_key: Optional[str] = None,
            search_type = None

    ) -> List[validator.EnhancedVectorSearchResult]:
        """
        Enhanced semantic search with:
        - Advanced filtering
        - Hybrid scoring
        - Pagination
        - Explainability
        - Server-side optimizations
        """
        try:
            # Validate pagination
            if page < 1 or page_size < 1:
                raise ValueError("Invalid pagination parameters")
            offset = (page - 1) * page_size

            # Validate store existence
            with self.SessionLocal() as session:
                store = session.query(VectorStore).filter(
                    VectorStore.collection_name == store_name,
                    VectorStore.status == validator.StatusEnum.active
                ).first()
            if not store:
                raise StoreNotFoundError(f"Vector store {store_name} not found")

            # Generate query embedding
            query_vector = self.file_processor.embedding_model.encode(
                [query_text],
                convert_to_numpy=True
            ).tolist()[0]

            # Parse filters to Qdrant format
            qdrant_filter = self._parse_advanced_filters(filters) if filters else None

            # Execute vector search
            raw_results = self.vector_manager.query_store(
                store_name=store_name,
                query_vector=query_vector,
                top_k=top_k,
                filters=qdrant_filter,
                score_threshold=score_threshold,
                offset=offset,
                limit=page_size,
                cache_key=cache_key
            )

            # Process and enhance results
            processed_results = []
            for result in raw_results:
                processed = self._process_result(
                    result,
                    store.id,
                    score_boosts,
                    explain
                )
                processed_results.append(processed)

            return processed_results

        except Exception as e:
            logging_utility.error(f"Search failed: {str(e)}")
            raise VectorStoreError(f"Search operation failed: {str(e)}")


    # NEW: Added helper methods for enhanced functionality
    def _parse_advanced_filters(self, filters: Dict) -> models.Filter:
        """Convert advanced filter syntax to Qdrant filters"""
        conditions = []

        for key, value in filters.items():
            # Handle logical operators
            if key.startswith("$"):
                if key == "$or":
                    or_conditions = [
                        self._parse_advanced_filters(cond)
                        for cond in value
                    ]
                    conditions.append(models.Filter(should=or_conditions))
                elif key == "$and":
                    and_conditions = [
                        self._parse_advanced_filters(cond)
                        for cond in value
                    ]
                    conditions.append(models.Filter(must=and_conditions))
                continue

            # Handle comparison operators
            if isinstance(value, dict):
                for op, op_value in value.items():
                    if op == "$gt":
                        conditions.append(models.FieldCondition(
                            key=f"metadata.{key}",
                            range=models.Range(gt=op_value)
                        ))
                    elif op == "$contains":
                        conditions.append(models.FieldCondition(
                            key=f"metadata.{key}",
                            match=models.MatchAny(any=[op_value])
                        ))
            else:
                # Default to exact match
                conditions.append(models.FieldCondition(
                    key=f"metadata.{key}",
                    match=models.MatchValue(value=value)
                ))

        return models.Filter(must=conditions) if conditions else None

    def _process_result(self, result, store_id, score_boosts, explain):
        """Apply scoring boosts and build explanations"""
        base_score = result['score']
        boosts = {}

        if score_boosts:
            for field, boost in score_boosts.items():
                # Handle nested metadata fields
                value = result['metadata']
                if '.' in field:
                    for part in field.split('.'):
                        value = value.get(part, None) if isinstance(value, dict) else None
                        if value is None:
                            break

                if value is not None:
                    base_score *= boost
                    boosts[field] = {
                        'value': value,
                        'boost': boost
                    }

        # Build explanation if requested
        explanation = None
        if explain:
            explanation = validator.SearchExplanation(
                base_score=result['score'],
                filters_passed=self._get_passed_filters(result),
                boosts_applied={k: v['boost'] for k, v in boosts.items()},
                final_score=base_score
            )

        return validator.EnhancedVectorSearchResult(
            text=result['text'],
            metadata=result.get('metadata', {}),
            score=base_score,
            vector_id=str(result['id']),
            store_id=store_id,
            explanation=explanation
        )


    def _get_passed_filters(self, result):
        """Identify which filters the result passed"""
        # Implementation note: This should compare result metadata against
        # the original query filters to determine which ones were matched
        # Current simplified version returns all filters
        return list(result.get('metadata', {}).keys())





    def batch_search(
            self,
            queries: List[str],
            store_name: str,
            top_k: int = 5,
            filters: Optional[Dict] = None
    ) -> Dict[str, List[validator.VectorStoreSearchResult]]:
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
                    VectorStore.status == validator.StatusEnum.active
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
                    store.status = validator.StatusEnum.deleted
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
                    VectorStore.status == validator.StatusEnum.active
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
                    VectorStore.status == validator.StatusEnum.active
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
        return validator.ProcessOutput(**result)

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


    def get_vector_stores_for_assistant(self, assistant_id: str) -> List[validator.VectorStoreRead]:
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
            return [validator.VectorStoreRead.model_validate(vs) for vs in assistant.vector_stores]

    def get_stores_by_user(self, user_id: str) -> List[validator.VectorStoreRead]:
        """
        Retrieve all vector stores belonging to a specific user.

        Args:
            user_id (str): The ID of the user whose stores are to be retrieved.

        Returns:
            List[VectorStoreRead]: A list of vector stores associated with the user.
        """
        try:
            with self.SessionLocal() as session:
                # Query the database for stores belonging to the user
                stores = session.query(VectorStore).filter(VectorStore.user_id == user_id).all()

                # Convert the ORM objects to Pydantic models
                return [validator.VectorStoreRead.model_validate(store) for store in stores]
        except Exception as e:
            logging_utility.error(f"Error retrieving stores for user {user_id}: {str(e)}")
            raise


    def health_check(self, deep_check: bool = False) -> Dict[str, Any]:
        """System health check with optional deep validation"""
        status = {
            "qdrant_connected": False,
            "database_connected": False,
            "storage_types": [],
            "collection_counts": {},
            "version": None,
            "metrics": {}
        }

        try:
            # Qdrant basic connectivity
            status["qdrant_connected"] = self.vector_manager.health_check()

            # Database connection check
            with self.SessionLocal() as session:
                session.execute(text("SELECT 1"))
                status["database_connected"] = True

            # Deep diagnostics
            if deep_check:
                # Version info
                status["version"] = self.vector_manager.client._client.openapi_client.models_api.get_version()

                # Storage metrics
                metrics = self.vector_manager.client._client.openapi_client.metrics_api.get_metrics()
                status["metrics"] = metrics.dict()

                # Collection stats
                collections = self.vector_manager.client.get_collections()
                status["collection_counts"] = {
                    "total": len(collections.collections),
                    "active": sum(1 for c in collections.collections if c.status == "green")
                }

                # File storage check
                test_file = Path("/tmp/healthcheck.txt")
                test_file.write_text("healthcheck")
                try:
                    self.add_files(test_file, "healthcheck", self)
                    status["storage_types"].append("local_files")
                finally:
                    test_file.unlink()
                    self.delete_file_from_store("healthcheck", str(test_file))

        except Exception as e:
            logging_utility.error(f"Deep health check failed: {str(e)}")
            status["error"] = str(e)

        return status

    def format_message_for_storage(self, message: validator.MessageRead, role) -> dict:
        """Properly structure messages with role at metadata level"""

        return {
            "text": message.content,
            "metadata": {
                # Maintain role in metadata but add explicit typing
                "message_role": role,  # Changed key to be explicit
                "created_at": message.created_at,
                "thread_id": message.thread_id,
                "sender_id": message.sender_id,
                "status": message.status,
                "run_id": message.run_id,
                "assistant_id": message.assistant_id,
                "meta_data": message.meta_data
            }
        }

    def store_message_in_vector_store(self, message, vector_store_id, role="user"):
        """Updated storage method with explicit role assignment"""
        logging_utility.info("Storing message in vector store %s", vector_store_id)

        try:
            # Validate message role before storage
            if role not in ["user", "assistant"]:
                raise ValueError(f"Invalid message role: {role}")


            formatted_message = self.format_message_for_storage(message=message, role=role)
            logging_utility.debug("Formatted message: %s", formatted_message)

            embedding = self.file_processor.embedding_model.encode(
                formatted_message["text"]
            )
            vector_as_floats = [float(val) for val in embedding]

            self.add_to_store(
                store_name=vector_store_id,
                texts=[formatted_message["text"]],
                vectors=[vector_as_floats],
                metadata=[formatted_message["metadata"]]
            )
            logging_utility.info("Message stored successfully")

        except Exception as e:
            logging_utility.error("Message storage failed: %s", str(e))
            raise
