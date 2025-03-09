import os
import json
from fastapi import FastAPI, WebSocket
from sqlalchemy import create_engine, text, inspect

from entities_api.models.models import Base
from entities_api.routers import api_router  # Importing the combined API router
from entities_api.services.logging_service import LoggingUtility
from entities_api.platform_tools.code_interpreter_handler import CodeExecutionHandler

# Initialize the logging utility
logging_utility = LoggingUtility()

# Update this with your actual database URL
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, echo=True)

# Secondary Engine for a Specific Use Case
SPECIAL_DB_URL = os.getenv("SPECIAL_DB_URL")
special_engine = create_engine(SPECIAL_DB_URL, echo=True) if SPECIAL_DB_URL else None

# Initialize the code execution handler
handler = CodeExecutionHandler()  # Ensure this class is implemented properly


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
        try:
            # Parse incoming data. Expecting thread_id, assistant_id, code, and optionally action_id.
            data = await websocket.receive_text()
            parsed_data = json.loads(data)
            thread_id = parsed_data.get("thread_id", "default_thread")
            assistant_id = parsed_data.get("assistant_id", "default_assistant")
            code = parsed_data.get("code")

            class DummyAction:
                def __init__(self, id):
                    self.id = id

            action = DummyAction(parsed_data.get("action_id", "default_action"))

            # Use _handle_code_interpreter as an async generator
            async for chunk in handler._handle_code_interpreter(thread_id, assistant_id, code, action):
                await websocket.send_text(chunk)

        except json.JSONDecodeError:
            await websocket.close(code=1003)

    if init_db:
        logging_utility.info("Initializing database")
        Base.metadata.create_all(bind=engine)
        with engine.connect() as connection:
            connection.execute(text("ALTER TABLE messages MODIFY COLUMN content TEXT"))

    return app


app = create_app()
