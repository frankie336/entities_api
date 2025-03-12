# main.py or app.py
import asyncio
from fastapi import FastAPI
from socketio import AsyncServer, ASGIApp
from sandbox_api.services.socketio_shell_service import SocketIOShellService
from sandbox_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()
app = FastAPI()

# Initialize Socket.IO with CORS enabled
sio = AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    engineio_options={'compression': False}
)

# Initialize the shell service on the /shell namespace
shell_service = SocketIOShellService(sio)

def create_app():
    app = FastAPI(
        title="Sandbox API",
        description="Integrated Socket.IO Shell Service",
        version="1.0"
    )

    # Mount Socket.IO with proper configuration
    app.mount("/socket.io", ASGIApp(sio))

    @app.get("/health")
    async def health_check():
        return {
            "status": "ok",
            "active_shell_sessions": len(shell_service.client_sessions)
        }

    return app

app = create_app()

# Export sio and shell_service for use in other modules
__all__ = ["sio", "shell_service", "app"]