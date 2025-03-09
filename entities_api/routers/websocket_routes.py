# entities_api/routers/websocket_routes.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
from entities_api.platform_tools.code_interpreter_handler import CodeInterpreterHandler

# Instantiate the handler (adjust this if you already have DI set up)
handler = CodeInterpreterHandler()

router = APIRouter()

@router.websocket("/execute")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        # Parse incoming data: expect thread_id, assistant_id, code, and optionally action_id.
        data = await websocket.receive_text()
        parsed_data = json.loads(data)
        thread_id = parsed_data.get("thread_id", "default_thread")
        assistant_id = parsed_data.get("assistant_id", "default_assistant")
        code = parsed_data.get("code", "")
        action_id = parsed_data.get("action_id", "default_action")

        # Create an Action-like object. In production, you might replace this with a proper model.
        class DummyAction:
            def __init__(self, id):
                self.id = id
        action = DummyAction(action_id)

        # Use _handle_code_interpreter as an async generator.
        async for chunk in handler._handle_code_interpreter(thread_id, assistant_id, code, action):
            # Send each JSON-formatted chunk to the client.
            await websocket.send_text(chunk)

    except json.JSONDecodeError:
        await websocket.close(code=1003)
    except WebSocketDisconnect:
        # Optionally log the disconnect event.
        pass
    except Exception as e:
        # Close the socket with an error code if something unexpected happens.
        await websocket.close(code=1011)
