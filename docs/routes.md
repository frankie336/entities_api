# 📘 API Endpoint Table

| Method   | Path                                                              | Name                             | Tags               | Summary                                                        |
|----------|-------------------------------------------------------------------|----------------------------------|--------------------|----------------------------------------------------------------|
| POST     | /actions                                                          | create_action                    | Actions            |                                                                |
| GET      | /actions/pending/{run_id}                                         | get_pending_actions              | Actions            |                                                                |
| GET      | /actions/{action_id}                                              | get_action                       | Actions            |                                                                |
| PUT      | /actions/{action_id}                                              | update_action_status             | Actions            |                                                                |
| DELETE   | /actions/{action_id}                                              | delete_action                    | Actions            |                                                                |
| POST     | /admin/users/{target_user_id}/keys                                | admin_create_api_key_for_user    | Admin, Admin       | Admin: Create API Key for User                                 |
| POST     | /assistants                                                       | create_assistant                 | Assistants         |                                                                |
| GET      | /assistants/{assistant_id}                                        | get_assistant                    | Assistants         |                                                                |
| PUT      | /assistants/{assistant_id}                                        | update_assistant                 | Assistants         |                                                                |
| GET      | /assistants/{assistant_id}/tools                                  | list_tools                       | Tools              |                                                                |
| POST     | /assistants/{assistant_id}/tools/{tool_id}                        | associate_tool_with_assistant    | Tools              |                                                                |
| DELETE   | /assistants/{assistant_id}/tools/{tool_id}                        | disassociate_tool_from_assistant | Tools              |                                                                |
| GET      | /assistants/{assistant_id}/vector-stores                          | list_assistant_stores            | Vector Stores      |                                                                |
| POST     | /assistants/{assistant_id}/vector-stores/{vector_store_id}/attach | attach_store                     | Vector Stores      |                                                                |
| DELETE   | /assistants/{assistant_id}/vector-stores/{vector_store_id}/detach | detach_store                     | Vector Stores      |                                                                |
| POST     | /completions                                                      | completions                      | Inference          | Asynchronous completions streaming endpoint (New Architecture) |
| GET      | /files/download                                                   | download_file                    | Files              | Download file via signed URL (no API key required)             |
| GET      | /files/{file_id}                                                  | retrieve_file_metadata           | Files              | Retrieve file metadata                                         |
| DELETE   | /files/{file_id}                                                  | delete_file_endpoint             | Files              | Delete a file                                                  |
| GET      | /files/{file_id}/base64                                           | get_file_as_base64               | Files              | Get file as Base64                                             |
| GET      | /files/{file_id}/signed-url                                       | generate_signed_url              | Files              | Generate a temporary signed URL (no API key required)          |
| GET      | /health                                                           | health_check                     | Main API, Health   |                                                                |
| POST     | /messages                                                         | create_message                   | Messages           |                                                                |
| POST     | /messages/assistant                                               | save_assistant_message           | Messages           |                                                                |
| POST     | /messages/tools                                                   | submit_tool_response             | Messages           |                                                                |
| GET      | /messages/{message_id}                                            | get_message                      | Messages           |                                                                |
| POST     | /monitor                                                          | register_run_monitoring          | Event Monitoring   |                                                                |
| POST     | /runs                                                             | create_run                       | Runs               |                                                                |
| GET      | /runs/{run_id}                                                    | get_run                          | Runs               |                                                                |
| GET      | /runs/{run_id}/actions/status                                     | get_actions_by_status            | Actions            |                                                                |
| POST     | /runs/{run_id}/cancel                                             | cancel_run                       | Runs               |                                                                |
| GET      | /runs/{run_id}/events                                             | stream_run_events                | Runs               | Stream run‑lifecycle events (SSE)                              |
| PUT      | /runs/{run_id}/status                                             | update_run_status                | Runs               |                                                                |
| GET      | /subscribe/{run_id}                                               | subscribe_to_run_events          | Event Monitoring   |                                                                |
| POST     | /threads                                                          | create_thread                    | Threads, Threads   |                                                                |
| GET      | /threads/user/{user_id}                                           | list_user_threads                | Threads, Threads   |                                                                |
| GET      | /threads/{thread_id}                                              | get_thread                       | Threads, Threads   |                                                                |
| DELETE   | /threads/{thread_id}                                              | delete_thread                    | Threads, Threads   |                                                                |
| PUT      | /threads/{thread_id}                                              | update_thread                    | Threads, Threads   |                                                                |
| GET      | /threads/{thread_id}/formatted_messages                           | get_formatted_messages           | Messages           |                                                                |
| GET      | /threads/{thread_id}/messages                                     | list_messages                    | Messages           |                                                                |
| PUT      | /threads/{thread_id}/metadata                                     | update_thread_metadata           | Threads, Threads   |                                                                |
| POST     | /tools                                                            | create_tool                      | Tools              |                                                                |
| GET      | /tools                                                            | list_tools                       | Tools              |                                                                |
| GET      | /tools/name/{name}                                                | get_tool_by_name                 | Tools              |                                                                |
| GET      | /tools/{tool_id}                                                  | get_tool                         | Tools              |                                                                |
| PUT      | /tools/{tool_id}                                                  | update_tool                      | Tools              |                                                                |
| DELETE   | /tools/{tool_id}                                                  | delete_tool                      | Tools              |                                                                |
| POST     | /uploads                                                          | upload_file_endpoint             | Files              | Upload a file                                                  |
| POST     | /users                                                            | create_user                      | Users, Users       |                                                                |
| GET      | /users/{user_id}                                                  | get_user                         | Users, Users       |                                                                |
| PUT      | /users/{user_id}                                                  | update_user                      | Users, Users       |                                                                |
| DELETE   | /users/{user_id}                                                  | delete_user                      | Users, Users       |                                                                |
| POST     | /users/{user_id}/apikeys                                          | create_api_key                   | API Keys, API Keys | Create API Key                                                 |
| GET      | /users/{user_id}/apikeys                                          | list_api_keys                    | API Keys, API Keys | List API Keys                                                  |
| GET      | /users/{user_id}/apikeys/{key_prefix}                             | get_api_key_details              | API Keys, API Keys | Get API Key Details                                            |
| DELETE   | /users/{user_id}/apikeys/{key_prefix}                             | revoke_api_key                   | API Keys, API Keys | Revoke API Key                                                 |
| GET      | /users/{user_id}/assistants                                       | list_assistants_by_user          | Assistants         |                                                                |
| POST     | /users/{user_id}/assistants/{assistant_id}                        | associate_assistant_with_user    | Assistants         |                                                                |
| DELETE   | /users/{user_id}/assistants/{assistant_id}                        | disassociate_assistant_from_user | Assistants         |                                                                |
| POST     | /vector-stores                                                    | create_vector_store              | Vector Stores      | Create Vector Store                                            |
| GET      | /vector-stores                                                    | list_my_vector_stores            | Vector Stores      | List current user's Vector Stores                              |
| GET      | /vector-stores/admin/by-user                                      | list_vector_stores_by_user       | Vector Stores      | (admin) list vector-stores for a given user_id                 |
| GET      | /vector-stores/lookup/collection                                  | get_vector_store_by_collection   | Vector Stores      | Get Vector Store by Collection Name                            |
| DELETE   | /vector-stores/{vector_store_id}                                  | delete_vector_store              | Vector Stores      | Delete Vector Store                                            |
| GET      | /vector-stores/{vector_store_id}                                  | get_vector_store                 | Vector Stores      |                                                                |
| POST     | /vector-stores/{vector_store_id}/files                            | add_file                         | Vector Stores      |                                                                |
| GET      | /vector-stores/{vector_store_id}/files                            | list_files                       | Vector Stores      |                                                                |
| DELETE   | /vector-stores/{vector_store_id}/files                            | delete_file                      | Vector Stores      |                                                                |
| PATCH    | /vector-stores/{vector_store_id}/files/{file_id}                  | update_file_status               | Vector Stores      |                                                                |
