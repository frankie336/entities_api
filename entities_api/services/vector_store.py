# entities_api/services/vector_store.py
import time
import uuid
from typing import List, Dict, Optional

from fastapi import HTTPException
from qdrant_client import QdrantClient
from qdrant_client.http import models

from entities_api.interfaces.base_vector_store import BaseVectorStore, StoreExistsError, VectorStoreError, \
    StoreNotFoundError
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class VectorStore(BaseVectorStore):
    def __init__(self, qdrant_client: QdrantClient):
        self.client = qdrant_client
        self.active_stores: Dict[str, dict] = {}
        logging_utility.info(f"Initialized VectorStore. Source: {__file__}")

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

    def add_to_store(self, store_name: str, texts: List[str], vectors: List[List[float]], metadata: List[dict]) -> dict:
        """Add text entries to vector store"""
        try:
            points = [
                models.PointStruct(
                    id=self._generate_vector_id(),
                    vector=vector,
                    payload={"text": text, "metadata": md, "timestamp": int(time.time())}
                ) for text, vector, md in zip(texts, vectors, metadata)
            ]

            operation = self.client.upsert(collection_name=store_name, points=points)
            return {"store": store_name, "added": len(points), "status": operation.status}

        except Exception as e:
            logging_utility.error(f"Store update failed: {str(e)}")
            raise VectorStoreError(f"Store update failed: {str(e)}")

    def query_store(self, store_name: str, query_vector: List[float], top_k: int = 5, filters: Optional[dict] = None) -> List[dict]:
        """Query store with optional filters"""
        try:
            query_filter = models.Filter(must=[
                models.FieldCondition(key=f"metadata.{k}", match=models.MatchValue(v))
                for k, v in (filters or {}).items()
            ]) if filters else None

            results = self.client.search(
                collection_name=store_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k
            )

            return [{
                "id": r.id,
                "score": r.score,
                "text": r.payload.get("text"),
                "metadata": r.payload.get("metadata")
            } for r in results]

        except Exception as e:
            logging_utility.error(f"Query failed: {str(e)}")
            raise VectorStoreError(f"Query failed: {str(e)}")

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

    def get_client(self):
        """Get the underlying Qdrant client instance"""
        return self.client