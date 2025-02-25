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
        """
        Searches the specified vector store using the provided query and additional parameters.
        """
        return self.vector_store_service.search_vector_store(
            store_name=store_name,
            query_text=query_text,
            top_k=top_k,
            filters=filters,
            score_threshold=score_threshold
        )

    def search_orchestrator(self, query: str, assistant_id: str, top_k: int = 5) -> List[VectorStoreSearchResult]:
        """
        Orchestrates the vector search process by dynamically passing the query and assistant_id.
        Retrieves the vector stores associated with the assistant and performs a search in each store.

        Args:
            query (str): The search query.
            assistant_id (str): The ID of the assistant.
            top_k (int): The number of top results to return per store.

        Returns:
            List[VectorStoreSearchResult]: Aggregated search results from all relevant vector stores.
        """
        # Retrieve the assistant details to get associated vector stores.
        assistant_service = client.assistant_service
        retrieved_assistant = assistant_service.retrieve_assistant(assistant_id=assistant_id)
        vector_stores = retrieved_assistant.vector_stores

        results: List[VectorStoreSearchResult] = []
        for store in vector_stores:
            store_results = self.vector_store_service.search_vector_store(
                store_name=store.collection_name,
                query_text=query,
                top_k=top_k
            )
            results.extend(store_results)

        return results
