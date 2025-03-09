# entities_api/routers/websocket_routes.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json

from entities_api.clients.client import logging_utility
from entities_api.main import app
from entities_api.platform_tools.code_interpreter.code_interpreter_service import  StreamingCodeExecutionHandler

# Instantiate the handler (adjust this if you already have DI set up)
handler = StreamingCodeExecutionHandler()

router = APIRouter()

@app.websocket("/ws/execute")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    handler = StreamingCodeExecutionHandler()  # Use the correct handler

    try:
        # Single execution per connection pattern
        data = await websocket.receive_text()
        parsed_data = json.loads(data)

        # Execute with streaming
        await handler.execute_code_streaming(
            websocket=websocket,
            code=parsed_data["code"],
            user_id=parsed_data.get("user_id", "anonymous")
        )

    except (json.JSONDecodeError, KeyError) as e:
        await websocket.close(code=1003)
    except WebSocketDisconnect:
        logging_utility.info("Client disconnected")
    finally:
        await websocket.close()
