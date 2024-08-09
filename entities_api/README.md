# Flexible State Management API

This package provides a robust and flexible state management solution for managing thread states in a conversational AI system. Built with FastAPI, this package ensures efficient and scalable state management with a focus on performance and ease of use.

## Features

- **FastAPI Integration**: Leverages the power and speed of FastAPI to provide a seamless API experience.
- **State Management**: Maintain and manage the state information of threads, allowing for more dynamic and interactive conversations.
- **Scalability**: Designed to handle a large number of concurrent users and threads efficiently.
- **Extensibility**: Easy to extend and customize according to specific requirements.

## Requirements

- Python 3.8+
- FastAPI
- SQLAlchemy
- Uvicorn
- Databases
- Pydantic

## Installation

To install the required dependencies, run the following command:

```bash
pip install -r requirements.txt
Usage
Running the Server
To start the FastAPI server, use the following command:
bash

Usage
Running the Server
To start the FastAPI server, use the following command:

uvicorn main:app --reload

This will start the server on http://127.0.0.1:8000.
API Endpoints
Create a Thread

Endpoint: /threads/
Method: POST
Request Body:

{
  "thread_id": "string",
  "state": "string"
}

Endpoint: /threads/{thread_id}
Method: GET
Response:

{
  "thread_id": "string",
  "state": "string"
}

Update Thread State

Endpoint: /threads/{thread_id}
Method: PUT
Request Body:

{
  "thread_id": "string",
  "state": "string"
}

Example
Here is a simple example to create a thread and update its state:
python

import httpx

# Create a thread
response = httpx.post("http://127.0.0.1:8000/threads/", json={"thread_id": "thread1", "initial_message": "Hello, world!"})
print(response.json())

# Update thread state
response = httpx.put("http://127.0.0.1:8000/threads/thread1", json={"state": "active"})
print(response.json())

# Get thread state
response = httpx.get("http://127.0.0.1:8000/threads/thread1")
print(response.json())

ollama-python/
├── api/
│   ├── __init__.py
│   ├── app.py
│   └── ...
├── db/
│   ├── __init__.py
│   ├── database.py
│   └── models.py
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
└── init_db.py
