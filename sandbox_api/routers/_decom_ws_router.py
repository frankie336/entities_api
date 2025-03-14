# ws_router.py
import json
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from sandbox_api.main import shell_service
from sandbox_api.services.code_execution import StreamingCodeExecutionHandler
from sandbox_api.services.logging_service import LoggingUtility
from sandbox_api.utils.sio import add_to_room, broadcast_to_room, remove_from_room

logging_utility = LoggingUtility()
router = APIRouter()





@router.websocket("/execute")
async def websocket_execute(websocket: WebSocket):
    """Handles code execution via WebSocket, managing rooms."""
    await websocket.accept()
    handler = StreamingCodeExecutionHandler()

    try:
        data = await websocket.receive_text()
        parsed_data = json.loads(data)

        user_id = parsed_data.get("user_id", "anonymous")
        room_name = f"execute_{user_id}"  # You can modify this logic for room naming
        add_to_room(room_name, websocket)  # Add the WebSocket to the room

        await handler.execute_code_streaming(
            websocket=websocket,
            code=parsed_data["code"],
            user_id=user_id
        )

        # Optionally, send a message to the room (e.g., "Code execution started")
        await broadcast_to_room(room_name, f"User {user_id} started code execution.", websocket)

    except (json.JSONDecodeError, KeyError):
        await websocket.close(code=1003)
    except WebSocketDisconnect:
        logging_utility.info("Client disconnected")
        remove_from_room(room_name, websocket)  # Remove from the room on disconnect
    except Exception as e:
        logging_utility.error(f"Unexpected error: {str(e)}")
        await websocket.close(code=1003)









