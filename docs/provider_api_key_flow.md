<pre>
+-----------------------------+
|        User Script          |
|-----------------------------|
| sync_stream.stream_chunks( |
|   ...,                      |
|   api_key='some_key' <──────┼─ START: Key provided here
| )                           |
+-----------------------------+
             |
             | api_key='some_key' passed as argument
             v
+---------------------------------+
| SynchronousInferenceStream      |
| (`sync_stream`)                 |
|---------------------------------|
| Method: stream_chunks()         |
| - Receives 'api_key' parameter  |
| - Calls internal async helper   |
|   `_stream_chunks_async()`      |
|   which calls...                |
|---------------------------------|
|   self.inference_client         |
|     .stream_inference_response( |
|       ...,                      |
|       api_key=api_key <─────────┼─ Key passed along
|     )                           |
+---------------------------------+
             |
             | api_key='some_key' passed as argument
             v
+---------------------------------+
| InferenceClient                 |
| (`client.inference`)            |
|---------------------------------|
| Method: stream_inference_response()|
| - Receives 'api_key' parameter  |
| - Creates `payload` dictionary  |
|   `{ ...,                      |
|     "api_key": api_key, <───────┼─ Key added to payload dict
|     ...}`                       |
| - Validates payload (incl. key) |
|   using `StreamRequest` model   |
| - Makes HTTP POST request       |
+---------------------------------+
             |
             | HTTP POST Request to /v1/completions
             | Body: JSON payload containing "api_key": "some_key"
             v
  =================== NETWORK ====================
             |
             v
+---------------------------------------------+
|           FastAPI Backend Service           |
|---------------------------------------------|
| Route: POST /v1/completions                 |
|---------------------------------------------|
| 1. Receives HTTP Request                    |
| 2. Parses JSON payload body                 |
| 3. Validates & populates Pydantic model:    |
|    `request: ValidationInterface.StreamRequest`|
|    -> request.api_key == 'some_key' <───────┼─ Key available in request object
+---------------------------------------------+
             |
             | `request` object (containing api_key) used by backend logic
             v
+---------------------------------+     +------------------------------------+
| InferenceProviderSelector /     | --> | Specific Provider Instance         |
| InferenceArbiter                |     | (e.g., Hyperbolic from request.provider)|
|---------------------------------|     |------------------------------------|
| - Selects provider instance     |     | Method: process_conversation()     |
|   based on `request.provider`   |     | - Receives thread_id, etc.         |
|   and `request.model`           |     | - *Likely* accesses `request.api_key`|
+---------------------------------+     |   internally for authentication    |
                                        |   when calling the actual service  |
                                        +------------------------------------+
                                                         | Uses 'some_key' for authentication
                                                         v
                                              =================== NETWORK ====================
                                                         | API Call to the specific provider's API
                                                         v
                                              +-----------------------------+
                                              | External AI Service         |
                                              | (e.g., Hyperbolic API)      |
                                              +-----------------------------+
</pre>
