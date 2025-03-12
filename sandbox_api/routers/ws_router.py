import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sandbox_api.services.logging_service import LoggingUtility
from sandbox_api.services.code_execution import StreamingCodeExecutionHandler
from sandbox_api.services.remote_shell_service import RemoteShellService
from typing import List

router = APIRouter()
logging_utility = LoggingUtility()
shell_service = RemoteShellService()

# Dictionary to manage connections by room/user_id
rooms = {}

# Utility function to add/remove clients to/from rooms
def add_to_room(room_name: str, websocket: WebSocket):
    if room_name not in rooms:
        rooms[room_name] = []
    rooms[room_name].append(websocket)

def remove_from_room(room_name: str, websocket: WebSocket):
    if room_name in rooms and websocket in rooms[room_name]:
        rooms[room_name].remove(websocket)

async def broadcast_to_room(room_name: str, message: str, sender: WebSocket):
    """Broadcast message to all clients in the specified room."""
    if room_name in rooms:
        for connection in rooms[room_name]:
            if connection != sender:
                await connection.send_text(message)

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
    """Delegates shell session handling to RemoteShellService with room management."""
    await websocket.accept()

    try:
        data = await websocket.receive_text()
        parsed_data = json.loads(data)
        user_id = parsed_data.get("user_id", "anonymous")
        room_name = f"shell_{user_id}"  # Again, dynamic room naming
        add_to_room(room_name, websocket)  # Add WebSocket to the room

        # Delegate shell session handling to RemoteShellService
        try:
            await shell_service.start_shell_session(websocket)
        except Exception as e:
            logging_utility.error(f"Error in shell session: {str(e)}")
            await websocket.close(code=1003)

        # Optionally, broadcast that the shell session started
        await broadcast_to_room(room_name, f"User {user_id} started a shell session.", websocket)

    except (json.JSONDecodeError, KeyError):
        await websocket.close(code=1003)
    except WebSocketDisconnect:
        logging_utility.info("Client disconnected")
        remove_from_room(room_name, websocket)  # Remove from room on disconnect
    except Exception as e:
        logging_utility.error(f"Unexpected error: {str(e)}")
        await websocket.close(code=1003)
