from entities_api.schemas import VectorStoreSearchResult
from entities_api.services.vector_store_service import VectorStoreService
from entities_api.schemas import VectorStoreRead, VectorStoreStatus
from entities_api import OllamaClient
from entities_api.vectorsthis import vector_store
from entities_api.schemas import VectorStoreRead, VectorStoreStatus


client = OllamaClient()

class VectorSearchHandler:
    def __init__(self):

        self.vector_store_service = VectorStoreService()

    def search_results(self, store_name: str, query_text: str,
                       top_k: int = 5, filters: dict | None = None,
                       score_threshold: float = 0.5) -> list[VectorStoreSearchResult]:

            return self.vector_store_service.search_vector_store()

    def search_orchestrator(self, query: str, top_k: int, assistant_id: str):
        """Now accepts both tool arguments and assistant_id"""
        assistant_service = client.assistant_service
        retrieve_assistant = assistant_service.retrieve_assistant(assistant_id=assistant_id)
        vector_stores = retrieve_assistant.vector_stores

        # Actual search implementation using query/top_k
        results = []
        for store in vector_stores:
            store_results = self.vector_store_service.search_vector_store(
                store_name=store.collection_name,
                query_text=query,
                top_k=top_k
            )
            results.extend(store_results)

        return results


