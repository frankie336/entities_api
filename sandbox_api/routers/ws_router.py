# ws_router.py
import json

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

@router.websocket("/shell")
async def websocket_shell(websocket: WebSocket):
    """Delegates shell session handling to SocketIOShellService with room management."""
    await websocket.accept()

    try:
        # ------------------------------------
        # Deals with registering clients to sio
        # rooms.
        # Receive initial data from the client
        #--------------------------------------
        data = await websocket.receive_text()
        parsed_data = json.loads(data)
        user_id = parsed_data.get("user_id", "anonymous")
        room_name = f"shell_{user_id}"  # Dynamic room naming

        # Delegate shell session handling to SocketIOShellService
        try:
            sid = websocket.headers.get("sid")  # Extract Socket.IO session ID
            await shell_service._create_client_session(sid)
        except Exception as e:
            logging_utility.error(f"Error in shell session: {str(e)}")
            await websocket.close(code=1003)

        # Optionally, broadcast that the shell session started
        await shell_service._broadcast_to_room(room_name, f"User {user_id} started a shell session.")

    except (json.JSONDecodeError, KeyError):
        await websocket.close(code=1003)
    except WebSocketDisconnect:
        logging_utility.info("Client disconnected")
    except Exception as e:
        logging_utility.error(f"Unexpected error: {str(e)}")
        await websocket.close(code=1003)