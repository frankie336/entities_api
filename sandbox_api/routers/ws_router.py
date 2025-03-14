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


# In ws_router.py
@router.websocket("/shell")
async def websocket_shell(websocket: WebSocket):
    """Handle both WebSocket and Socket.IO shell sessions"""
    await websocket.accept()
    try:
        # Initial handshake with version check
        data = await websocket.receive_text()
        parsed_data = json.loads(data)

        # Validate protocol version
        if parsed_data.get('version') != '1.2':
            await websocket.send_json({
                'error': 'Unsupported client version',
                'supported_versions': ['1.2']
            })
            await websocket.close(code=1008)
            return

        # Get connection parameters
        thread_id = parsed_data.get('thread_id')
        user_id = parsed_data.get('user_id', 'anonymous')

        if not thread_id:
            await websocket.send_json({'error': 'thread_id required'})
            await websocket.close(code=1003)
            return

        # Create virtual Socket.IO session
        sid = f"ws_{datetime.utcnow().timestamp()}"

        # Simulate Socket.IO connection
        await shell_service.handle_connect(
            sid=sid,
            environ={},
            auth={'thread_id': thread_id, 'user_id': user_id}
        )

        # Bridge WebSocket messages to Socket.IO service
        while True:
            message = await websocket.receive_text()
            await shell_service.handle_command(sid, {'command': message})

    except WebSocketDisconnect:
        logging_utility.info("Client disconnected")
        await shell_service.handle_disconnect(sid)
    except Exception as e:
        logging_utility.error(f"Connection error: {str(e)}")
        await websocket.close(code=1011)
