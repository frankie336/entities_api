from entities_api import OllamaClient
from entities_api.schemas import VectorStoreSearchResult
from entities_api.services.vector_store_service import VectorStoreService
from typing import Optional, List

client = OllamaClient()

class VectorSearchHandler:
    def __init__(self):
        self.vector_store_service = VectorStoreService()

    def search_results(self, store_name: str, query_text: str,
                       top_k: int = 5, filters: Optional[dict] = None,
                       score_threshold: float = 0.5) -> List[VectorStoreSearchResult]:
        return self.vector_store_service.search_vector_store()

    def search_orchestrator(self, query: str, assistant_id: str, top_k=5) -> List[VectorStoreSearchResult]:
        """Now accepts both tool arguments and assistant_id"""
        assistant_service = client.assistant_service
        retrieve_assistant = assistant_service.retrieve_assistant(assistant_id=assistant_id)
        vector_stores = retrieve_assistant.vector_stores

        # Actual search implementation using query/top_k
        results: List[VectorStoreSearchResult] = []
        for store in vector_stores:
            store_results = self.vector_store_service.search_vector_store(
                store_name=store.collection_name,
                query_text=query,
                top_k=top_k
            )
            results.extend(store_results)

        return results
