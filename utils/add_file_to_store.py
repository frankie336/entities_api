from src.entities_api import OllamaClient


"""
Adding a .pdf to an existing vector store
"""
client = OllamaClient()
user_service = client.user_service
user = user_service.create_user(name="test")
vector_service = client.vector_service


vector_store = vector_service.create_vector_store( name="hot_fire_test",
                                    user_id=user.id
    )
print(print(vector_store))



test_file_path = "Donoghue_Stevenson.pdf"
file = vector_service.add_files(file_path=test_file_path, destination_store=vector_store.id)

# Verify store content (using the vector manager directly)
store_info = vector_service.vector_manager.get_store_info(vector_store.collection_name)
print(f"Store info: {store_info}")

search = vector_service.search_vector_store(
    store_name=vector_store.collection_name,
    query_text="House of Lords. It created the modern concept of negligence",

)
print(search)


attach = vector_service.attach_vector_store_to_assistant(vector_store_id=vector_store.collection_name, assistant_id="asst_taQHpSGaE8xuui1BQpIgqg")
print(attach)
