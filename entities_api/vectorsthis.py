from pathlib import Path

from together.cli.api.files import retrieve

from entities_api import OllamaClient
from entities_api.services.file_processor import FileProcessor


client = OllamaClient()
user_service = client.user_service

# Create user
#user = user_service.create_user(name="test_user")

# Create vector store
#vector_service = client.vector_service
#vector_store = vector_service.create_vector_store( name="hot_fire_test",
#                                    user_id=user.id
#    )

#print(print(vector_store))
#test_file_path = Path("test_file.txt")
#test_file_path.write_text("This is a test document for the vector store.", encoding="utf-8")
#print(f"Created test file at: {test_file_path}")


#file = vector_service.add_files(file_path=test_file_path, destination_store=vector_store.id)

#print(f"File processed successfully: {file}")


# Verify store content (using the vector manager directly)
#store_info = vector_service.vector_manager.get_store_info(vector_store.collection_name)
#print(f"Store info: {store_info}")
#vector_service.attach_vector_store_to_assistant(vector_store_id=vector_store.id, assistant_id="asst_taQHpSGaE8xuui1BQpIgqg")




assistant_service = client.assistant_service
retrieve_assistant = assistant_service.retrieve_assistant(assistant_id="asst_Qsnc9bfUhCWft30YsqrBw0")
print(retrieve_assistant.vector_stores)
#[VectorStoreRead(id='vect_aEYwjwJFDdaLjLCDCt1swa', name='pilot_wave3', user_id='user_BNVJkhbOxMAaxuNgdyuPg9', collection_name='vect_aEYwjwJFDdaLjLCDCt1swa', vector_size=384, distance_metric='COSINE', created_at=1740274389, updated_at=None, status=<VectorStoreStatus.active: 'active'>, config={'example': 'value'}, file_count=0), VectorStoreRead(id='vect_DkltjLT7UWpIzS5N8vGDNW', name='pilot_wave3', user_id='user_sLThxPDOfLXx4UpedS0Ahh', collection_name='vect_DkltjLT7UWpIzS5N8vGDNW', vector_size=384, distance_metric='COSINE', created_at=1740274336, updated_at=None, status=<VectorStoreStatus.active: 'active'>, config={'example': 'value'}, file_count=0), VectorStoreRead(id='vect_e9huFSfg7bA6GgvcbfeZBg', name='pilot_wave3', user_id='user_t7Eu6QBrgoQwRBrUfFogaR', collection_name='vect_e9huFSfg7bA6GgvcbfeZBg', vector_size=384, distance_metric='COSINE', created_at=1740284139, updated_at=None, status=<VectorStoreStatus.active: 'active'>, config={'example': 'value'}, file_count=0), VectorStoreRead(id='vect_JuO48ra6qanur9mi6sTsQu', name='pilot_wave3', user_id='user_xEbVoBqUPNHQy8Qcy5mKSt', collection_name='vect_JuO48ra6qanur9mi6sTsQu', vector_size=384, distance_metric='COSINE', created_at=1740284004, updated_at=None, status=<VectorStoreStatus.active: 'active'>, config={'example': 'value'}, file_count=0)]
