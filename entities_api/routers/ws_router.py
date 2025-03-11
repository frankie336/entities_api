# entities_api/routers/ws_router.py
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from entities_api.services.logging_service import LoggingUtility
from entities_api.platform_tools.code_interpreter.streaming_handler import StreamingCodeExecutionHandler

router = APIRouter()
logging_utility = LoggingUtility()

@router.websocket("/execute")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    handler = StreamingCodeExecutionHandler()

    try:
        data = await websocket.receive_text()
        parsed_data = json.loads(data)

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