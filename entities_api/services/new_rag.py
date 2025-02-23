from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from entities_api.services.vector_store_manager import VectorStoreManager
from entities_api.services.file_processor import FileProcessor

def main():
    # Initialize components
    qdrant = QdrantClient("localhost:6333")  # Or use ":memory:" for testing
    vector_service = VectorStoreManager(qdrant)
    file_processor = FileProcessor()
    embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

    # Process and store a file
    store_info = file_processor.process_and_store(
        file_path="example.txt",
        vector_service=vector_service,
        embedding_model=embedding_model
    )

    # Perform a search
    results = vector_service.query_store(
        store_name=store_info["name"],
        query_vector=embedding_model.encode("llama communication").tolist()



    )

    print(results)

if __name__ == "__main__":
    main()