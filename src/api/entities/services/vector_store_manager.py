# entities/services/vector_store_manager.py
import time
import uuid
from typing import List, Dict, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

from entities.interfaces.base_vector_store import BaseVectorStore, StoreExistsError, VectorStoreError, \
    StoreNotFoundError
from entities.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class VectorStoreManager(BaseVectorStore):
    def __init__(self):


        self.client = QdrantClient(url="http://localhost:6333")

        self.active_stores: Dict[str, dict] = {}
        logging_utility.info(f"Initialized VectorStoreManager. Source: {__file__}")
        prefer_grpc = True  # Better for bulk operations


    def _generate_vector_id(self) -> str:
        """Generate unique vector ID using UUID4"""
        return str(uuid.uuid4())

    def create_store(self, store_name: str, vector_size: int = 384, distance: str = "COSINE") -> dict:
        """Create a new vector store for text embeddings"""
        try:
            if store_name in self.active_stores:
                raise StoreExistsError(f"Store {store_name} exists")

            self.client.create_collection(
                collection_name=store_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance[distance]
                )
            )


            self.active_stores[store_name] = {
                "created_at": int(time.time()),
                "vector_size": vector_size,
                "distance": distance
            }
            return {"name": store_name, "status": "created"}

        except StoreExistsError as e:
            logging_utility.error(f"Store creation failed: {str(e)}")
            raise
        except Exception as e:
            logging_utility.error(f"Unexpected error: {str(e)}")
            raise VectorStoreError(f"Store creation failed: {str(e)}")

    def create_store_for_file_type(self, file_type: str) -> dict:
        """Create store optimized for text files"""
        if file_type != "text":
            raise ValueError("Only text files are currently supported")

        store_name = f"text_store_{int(time.time())}"
        return self.create_store(store_name, vector_size=384, distance="COSINE")


        def _validate_vectors(self, vectors: List[List[float]]):
            """Ensure vector dimensions match expectations"""
            if not vectors:
                raise ValueError("Empty vectors list")

            expected_size = len(vectors[0])
            for i, vec in enumerate(vectors):
                if len(vec) != expected_size:
                    raise ValueError(
                        f"Vector {i} has invalid size {len(vec)} "
                        f"(expected {expected_size})"
                    )
                if not all(isinstance(v, float) for v in vec):
                    raise TypeError(f"Vector {i} contains non-float values")


    def add_to_store(self, store_name: str, texts: List[str],
                     vectors: List[List[float]], metadata: List[dict]):
        """Validate vectors before insertion"""
        self._validate_vectors(vectors)

        return self.client.upsert(
            collection_name=store_name,
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),  # Generate unique IDs
                    vector=vector,
                    payload={
                        "text": text,
                        "metadata": meta  # Store metadata under dedicated key
                    }
                )
                for text, vector, meta in zip(texts, vectors, metadata)
            ]
        )

    def _validate_vectors(self, vectors: List[List[float]]):
        """Ensure vector dimensions match expectations"""
        if not vectors:
            raise ValueError("Empty vectors list")

        expected_size = len(vectors[0])
        for i, vec in enumerate(vectors):
            if len(vec) != expected_size:
                raise ValueError(
                    f"Vector {i} has invalid size {len(vec)} "
                    f"(expected {expected_size})"
                )
            if not all(isinstance(v, float) for v in vec):
                raise TypeError(f"Vector {i} contains non-float values")


    def query_store(
        self,
        store_name: str,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[models.Filter] = None,
        score_threshold: float = 0.0,
        offset: int = 0,
        limit: Optional[int] = None,
        **kwargs
    ) -> List[dict]:
        """
        Enhanced store query with:
        - Server-side filtering
        - Pagination support
        - Score thresholding
        - Advanced Qdrant filters
        """
        try:
            # Use limit if provided, otherwise use top_k
            actual_limit = limit if limit is not None else top_k

            results = self.client.search(
                collection_name=store_name,
                query_vector=query_vector,
                query_filter=filters,
                limit=actual_limit,
                offset=offset,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False
            )

            return [{
                "id": r.id,
                "score": r.score,
                "text": r.payload.get("text"),
                "metadata": r.payload.get("metadata", {})
            } for r in results]

        except Exception as e:
            logging_utility.error(f"Query failed: {str(e)}")
            raise VectorStoreError(f"Query failed: {str(e)}")

    def delete_file_from_store(self, store_name: str, file_path: str) -> dict:
        """Delete all vectors associated with a specific file"""
        logging_utility.info(f"Deleting file '{file_path}' from store '{store_name}'")

        try:
            # Delete vectors matching the file path
            self.client.delete(
                collection_name=store_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[models.FieldCondition(
                            key="metadata.source",
                            match=models.MatchValue(value=file_path)
                        )]
                    )
                )
            )

            return {
                "deleted_file": file_path,
                "store_name": store_name,
                "status": "success"
            }

        except Exception as e:
            logging_utility.error(f"File deletion failed: {str(e)}")
            raise VectorStoreError(f"Could not delete file: {str(e)}")


    def delete_store(self, store_name: str) -> dict:
        """Delete a vector store with confirmation"""
        logging_utility.info(f"Deleting store '{store_name}'. Source: {__file__}")

        if store_name not in self.active_stores:
            raise StoreNotFoundError(f"Store {store_name} not found")

        try:
            self.client.delete_collection(store_name)
            del self.active_stores[store_name]
            logging_utility.info(f"Store '{store_name}' deleted successfully. Source: {__file__}")
            return {"name": store_name, "status": "deleted"}

        except Exception as e:
            logging_utility.error(f"Error deleting store '{store_name}': {str(e)}. Source: {__file__}")
            raise VectorStoreError(f"Deletion failed: {str(e)}")

    def get_store_info(self, store_name: str) -> dict:
        """Get detailed information about a vector store"""
        logging_utility.info(f"Getting info for store '{store_name}'. Source: {__file__}")

        if store_name not in self.active_stores:
            raise StoreNotFoundError(f"Store {store_name} not found")

        try:
            collection_info = self.client.get_collection(store_name)
            return {
                "name": store_name,
                "status": "active",
                "vectors_count": collection_info.points_count,
                "configuration": {
                    "vector_size": collection_info.config.params.vectors.size,
                    "distance": collection_info.config.params.vectors.distance.name
                },
                "created_at": self.active_stores[store_name]["created_at"]
            }
        except Exception as e:
            logging_utility.error(f"Error getting info for '{store_name}': {str(e)}. Source: {__file__}")
            raise VectorStoreError(f"Info retrieval failed: {str(e)}")

    def list_store_files(self, store_name: str) -> List[str]:
        """List unique source files in a vector store"""
        logging_utility.info(f"Listing files in store '{store_name}'. Source: {__file__}")

        try:
            # Get all points with scroll API
            records = []
            next_offset = None

            while True:
                # Get batch of points
                records_batch, next_offset = self.client.scroll(
                    collection_name=store_name,
                    limit=100,
                    offset=next_offset,
                    with_payload=["metadata.source"]
                )

                # Add valid file sources
                for record in records_batch:
                    source = record.payload.get("metadata", {}).get("source")
                    if source and isinstance(source, str):
                        records.append(source)

                # Break loop if no more results
                if next_offset is None or not records_batch:
                    break

            # Return unique sorted list of file paths
            return sorted(list(set(records)))

        except Exception as e:
            logging_utility.error(f"File listing failed: {str(e)}. Source: {__file__}")
            raise VectorStoreError(f"Could not list files: {str(e)}")

    def get_client(self):
        """Get the underlying Qdrant client instance"""
        return self.client

    def get_point_by_id(self, store_name: str, point_id: str) -> dict:
        """Retrieve a specific point by its ID"""
        pass

    def health_check(self) -> bool:
        """Perform thorough health check of Qdrant connection"""
        try:
            # Basic ping check
            start_time = time.monotonic()
            response = self.client._client.openapi_client.models_api.ready()
            if not response.status == "ok":
                raise VectorStoreError("Qdrant readiness check failed")

            # Validate storage connectivity
            collections = self.client.get_collections()
            if not isinstance(collections.collections, list):
                raise VectorStoreError("Invalid collections response")

            # Performance check (simple query)
            test_vector = [0.0] * 384  # Match default vector size
            self.client.search(
                collection_name="healthcheck",
                query_vector=test_vector,
                limit=1,
                with_payload=False,
                timeout=1.0
            )

            latency = time.monotonic() - start_time
            if latency > 2.0:  # 2 second threshold
                logging_utility.warning(f"Qdrant latency warning: {latency:.2f}s")

            return True

        except Exception as e:
            logging_utility.error(f"Vector store health check failed: {str(e)}")
            return False


