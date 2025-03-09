import os
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import create_engine, text
from entities_api.models.models import Base
from entities_api.routers import api_router
from entities_api.services.logging_service import LoggingUtility
from entities_api.platform_tools.code_interpreter.code_interpreter_service import CodeExecutionService
from entities_api.platform_tools.code_interpreter.streaming_handler import StreamingCodeExecutionHandler

# Initialize the logging utility
logging_utility = LoggingUtility()

# Update this with your actual database URL
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, echo=True)

# Secondary Engine for a Specific Use Case
SPECIAL_DB_URL = os.getenv("SPECIAL_DB_URL")
special_engine = create_engine(SPECIAL_DB_URL, echo=True) if SPECIAL_DB_URL else None

# Initialize the code execution handler
handler = CodeExecutionService()  # Ensure this class is implemented properly

def create_app(init_db=True):
    logging_utility.info("Creating FastAPI app")
    app = FastAPI()

    # Include API routers
    app.include_router(api_router, prefix="/v1")  # All routes under /v1

    @app.get("/")
    def read_root():
        logging_utility.info("Root endpoint accessed")
        return {"message": "Welcome to the API!"}

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



    if init_db:
        logging_utility.info("Initializing database")
        Base.metadata.create_all(bind=engine)
        with engine.connect() as connection:
            connection.execute(text("ALTER TABLE messages MODIFY COLUMN content TEXT"))

    return app


app = create_app()
