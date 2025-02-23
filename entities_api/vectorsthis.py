from pathlib import Path

from together.cli.api.files import retrieve

from entities_api import OllamaClient
from entities_api.services.file_processor import FileProcessor


client = OllamaClient()
user_service = client.user_service

# Create user
user = user_service.create_user(name="test_user")

# Create vector store
vector_service = client.vector_service
vector_store = vector_service.create_vector_store( name="pilot_wave3",
                                    user_id=user.id
    )

print(print(vector_store))
test_file_path = Path("test_file.txt")
test_file_path.write_text("This is a test document for the vector store.", encoding="utf-8")
print(f"Created test file at: {test_file_path}")


file = vector_service.add_files(file_path=test_file_path, destination_store=vector_store.id)
print(f"File processed successfully: {file}")


# Verify store content (using the vector manager directly)
store_info = vector_service.vector_manager.get_store_info(vector_store.collection_name)
print(f"Store info: {store_info}")

vector_service.attach_vector_store_to_assistant(vector_store_id=vector_store.id, assistant_id="asst_taQHpSGaE8xuui1BQpIgqg")




#assistant_service = client.assistant_service
#retrieve_assistant = assistant_service.retrieve_assistant(assistant_id="asst_Qsnc9bfUhCWft30YsqrBw0")
#print(retrieve_assistant.vector_stores)

