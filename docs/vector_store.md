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
from entities_api import OllamaClient  
# Initialize the client
client = OllamaClient()

# Create user
user = user_service.create_user(name="test_user")

# Create vector store
vector_service = client.vector_service
vector_store = vector_service.create_vector_store( name="pilot_wave",
                                    user_id=user.id
    )


```



**Adding a  single file to the vector store**

```python

file = vector_service.add_files(file_path=test_file_path, 
                                destination_store=vector_store.id)

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



