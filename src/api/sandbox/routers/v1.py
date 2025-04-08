import json

from fastapi import Query, WebSocket, WebSocketDisconnect
from fastapi.routing import APIRouter
from sandbox.services.code_execution import StreamingCodeExecutionHandler
from sandbox.services.logging_service import LoggingUtility
from sandbox.services.room_manager import RoomManager
from sandbox.services.shell_session import PersistentShellSession

logging_utility = LoggingUtility()
v1_router = APIRouter()  # No prefix here
room_manager = RoomManager()


@v1_router.websocket("/execute")
async def websocket_execute(websocket: WebSocket):
    """Handles code execution via WebSocket."""
    await websocket.accept()
    handler = StreamingCodeExecutionHandler()

    try:
        data = await websocket.receive_text()
        parsed_data = json.loads(data)

        # Validate input
        if "code" not in parsed_data:
            await websocket.send_json({"error": "Missing required field: code"})
            await websocket.close(code=1003)
            return

        await handler.execute_code_streaming(
            websocket=websocket,
            code=parsed_data["code"],
            user_id=parsed_data.get("user_id", "anonymous"),
        )

    except json.JSONDecodeError:
        await websocket.send_json({"error": "Invalid JSON input"})
        await websocket.close(code=1003)
    except KeyError as e:
        await websocket.send_json({"error": f"Missing required field: {str(e)}"})
        await websocket.close(code=1003)
    except WebSocketDisconnect:
        logging_utility.info("Client disconnected")
    except Exception as e:
        logging_utility.error(f"Unexpected error: {str(e)}")
        await websocket.send_json({"error": "Internal server error"})
        await websocket.close(code=1011)


@v1_router.websocket("/computer")
async def websocket_endpoint(
    websocket: WebSocket, room: str = Query("default"), elevated: bool = Query(False)
):
    """
    WebSocket endpoint for interactive computer sessions.

    :param websocket: The WebSocket connection.
    :param room: The session room ID.
    :param elevated: Whether to start the computer with sudo privileges.
    """
    session = PersistentShellSession(websocket, room, room_manager, elevated=elevated)
    await session.start()
