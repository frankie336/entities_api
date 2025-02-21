# entities_api/clients/client_vector_service.py
import httpx
from entities_api.schemas import VectorStoreCreate, VectorStoreRead
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class VectorStoreClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("VectorStoreClient initialized with base_url: %s", self.base_url)

    def create_vector_store(self, store_data: VectorStoreCreate) -> VectorStoreRead:
        """Create a new vector store via the API"""
        logging_utility.info("Creating vector store with data: %s", store_data.dict())
        try:
            response = self.client.post("/v1/vector-stores", json=store_data.dict())
            response.raise_for_status()
            created_store = response.json()
            validated_store = VectorStoreRead(**created_store)
            logging_utility.info("Vector store created successfully with ID: %s", validated_store.id)
            return validated_store
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating vector store: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating vector store: %s", str(e))
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()