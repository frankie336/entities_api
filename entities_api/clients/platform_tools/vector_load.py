# Tool creation and association functions
from entities_api.clients.client import OllamaClient

client = OllamaClient()
user_name='test_case'
# Create user
user = client.user_service.create_user(name="test_case")
userid = user.id
print(f"User created: ID: {userid}")
from entities_api.clients.client_vector_service import VectorStoreClient
vector_store = VectorStoreClient()

store = vector_store.create_vector_store(name="yes_123_yes",
                                         user_id=user.id,
                                         config=None
                                         )


print(store)
