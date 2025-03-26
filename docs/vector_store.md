# Vector Store

## Overview

[![PyPI Version](https://img.shields.io/pypi/v/your-package-name)](https://pypi.org/project/your-package-name/)
[![Python Versions](https://img.shields.io/pypi/pyversions/your-package-name)](https://pypi.org/project/your-package-name/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

A high-performance vector storage and retrieval system designed for AI/ML workflows. This implementation provides:

✨ **Semantic Search**  
🔍 **Nearest Neighbor Retrieval**  
📈 **Scalable Embedding Storage**  
🤖 **ML Framework Integration**

Associated methods can be used to extend the memory and contextual recall of AI assistants beyond the context window, allowing for Retrieval Augmented Generations, (RAG).  

**Create a Vector Store**

```python
from src.api.entities import CommonEntitiesInternalInterface

# Initialize the client
client = CommonEntitiesInternalInterface()

# Create user
user = user_service.create_user(name="test_user")

# Create vector store
vector_service = client.vector_service
vector_store = vector_service.create_vector_store(name="pilot_wave",
                                                  user_id=user.id
                                                  )


```



**Adding a  single file to the vector store**

```python

file = vector_service.add_files(file_path="Donoghue_Stevenson.pdf", 
                                destination_store=vector_store.id)

```

Metadata is automatically generated and attached to  each chunk. 

**Example Metadata Output:**

```plaintext

{
    "chunk_id": "document_chunk0023",
    "page_number": 5,
    "start_line": 12,
    "end_line": 15,
    "total_lines": 4,
    "partial_line": false,
    "token_count": 125,
    "author": "Jane Smith",
    "title": "Legal Analysis of Duty of Care"
}

```


**Adding a  single file with custom metadata**

```python

custom_metadata = {
    "case_year": 1932,
    "jurisdiction": "UK-Scotland",
    "legal_topic": "Negligence",
    "citation": "[1932] UKHL 100",
    "significance": "Landmark case establishing neighbor principle"
}


file = vector_service.add_files(
    file_path=Path("Donoghue_v_Stevenson.pdf"),
    destination_store="landmark_cases",
    user_metadata=custom_metadata,
    source_url="https://legalarchive.org/cases/UKHL/1932/100"
)


```


**Example Metadata Output:**

```plaintext

sample_chunk_metadata = {
    "chunk_id": "Donoghue_v_Stevenson_chunk0023",
    "source": "Donoghue_v_Stevenson.pdf",
    "document_type": "pdf",
    "page_number": 12,
    "start_line": 45,
    "end_line": 52,
    "total_lines": 8,
    "token_count": 127,
    
    # Custom metadata fields
    "case_year": 1932,
    "jurisdiction": "UK-Scotland",
    "legal_topic": "Negligence",
    "citation": "[1932] UKHL 100",
    "significance": "Landmark case establishing neighbor principle",
    
    # System-generated fields
    "retrieved_date": "2025-02-23T14:30:45.123456",
    "author": "Lord Atkin",
    "publication_date": "1932-05-26",
    "title": "Opinion of the Court",
    "domain": "legalarchive.org",
    "embedding_model": "paraphrase-MiniLM-L6-v2"
}

```




**Verify store content**

```python

store_info = vector_service.vector_manager.get_store_info(vector_store.collection_name)
print(f"Store info: {store_info}")

```




**Attach a Vector Store to an Assistant**

```python


vector_service.attach_vector_store_to_assistant(vector_store_id=vector_store.id, assistant_id="asst_Qsnc9bfUhCWft30YsqrBw0")

assistant_service = client.assistant_service
retrieve_assistant = assistant_service.retrieve_assistant(assistant_id="asst_Qsnc9bfUhCWft30YsqrBw0")
print(retrieve_assistant.vector_stores)

```



