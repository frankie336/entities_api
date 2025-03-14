import asyncio
import json
import os
import pty
import subprocess
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from sandbox_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class WebSocketShellService:
    def __init__(self):
        self.client_sessions = {}  # Map WebSocket -> session info
        self.rooms = {}  # Map room names to sets of WebSocket connections
        self.logging_utility = LoggingUtility()
        self.namespace = "/shell"  # For logging purposes
        self.logging_utility.info(f"Initializing WebSocket Shell Service on namespace: {self.namespace}")

    # --- Room Management ---
    def add_to_room(self, room_name: str, websocket: WebSocket):
        if room_name not in self.rooms:
            self.rooms[room_name] = set()
            self.logging_utility.debug(f"Creating new room: {room_name}")
        self.rooms[room_name].add(websocket)
        self.logging_utility.info(f"Added connection {websocket} to room {room_name}. Current rooms: {self.rooms}")

    def remove_from_room(self, websocket: WebSocket):
        for room_name, clients in list(self.rooms.items()):
            if websocket in clients:
                clients.remove(websocket)
                self.logging_utility.info(f"Removed connection {websocket} from room {room_name}. Remaining clients: {clients}")
                if not clients:
                    del self.rooms[room_name]
                    self.logging_utility.info(f"Room {room_name} deleted")

    async def broadcast_to_room(self, room_name: str, message: dict, exclude_ws: WebSocket = None):
        self.logging_utility.debug(f"Broadcasting to room {room_name}. Excluding: {exclude_ws}")
        if room_name in self.rooms:
            for client in self.rooms[room_name]:
                if client != exclude_ws:
                    try:
                        await client.send_text(json.dumps(message))
                        self.logging_utility.info(f"Broadcasted message to {client}")
                    except Exception as e:
                        self.logging_utility.error(f"Failed to send message to {client}: {str(e)}", exc_info=True)

    # --- Session Management and Shell Interaction ---
    async def create_client_session(self, websocket: WebSocket):
        try:
            self.logging_utility.debug(f"Creating PTY session for connection {websocket}")
            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen(
                ["bash", "-i"],
                preexec_fn=os.setsid,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                bufsize=0,
                universal_newlines=True,
            )
        except Exception as e:
            self.logging_utility.error(f"Process creation failed: {str(e)}", exc_info=True)
            await websocket.close()
            return

        self.client_sessions[websocket] = {
            "process": proc,
            "master_fd": master_fd,
            "created_at": datetime.utcnow().isoformat()
        }
        os.close(slave_fd)
        self.logging_utility.info(f"Created new session for connection {websocket}")
        asyncio.create_task(self.stream_output(websocket))

    async def process_command(self, websocket: WebSocket, command: str):
        if websocket not in self.client_sessions:
            self.logging_utility.error(f"Invalid session for connection {websocket} for command execution")
            raise Exception("Session does not exist")
        session = self.client_sessions.get(websocket)
        if not session:
            self.logging_utility.error(f"No active session for connection {websocket}")
            raise Exception("Session not active")
        if session["process"].poll() is not None:
            self.logging_utility.error(f"Process has already terminated for connection {websocket}")
            raise Exception("Session not active")
        try:
            os.write(session['master_fd'], f"{command}\n".encode())
            self.logging_utility.debug(f"Written command to FD {session['master_fd']}")
        except OSError as e:
            self.logging_utility.error(f"Write error: {str(e)}")
            raise

    async def stream_output(self, websocket: WebSocket):
        session = self.client_sessions.get(websocket)
        if not session:
            self.logging_utility.warning(f"No session for connection {websocket} in stream_output")
            return

        reader = asyncio.StreamReader()
        transport = None
        try:
            self.logging_utility.debug(f"Starting output stream for connection {websocket}")
            transport, _ = await asyncio.get_event_loop().connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(reader),
                os.fdopen(session['master_fd'], 'rb')
            )
            while not reader.at_eof():
                data = await reader.read(4096)
                if data:
                    output = data.decode(errors='ignore')
                    # Determine the room for this connection.
                    room = None
                    for room_name, clients in self.rooms.items():
                        if websocket in clients:
                            room = room_name
                            break
                    if not room:
                        self.logging_utility.warning(f"No room found for connection {websocket}")
                        continue
                    self.logging_utility.debug(f"Emitting output to room {room} from connection {websocket}")
                    emit_data = {
                        'content': output,
                        'thread_id': room,
                        'timestamp': datetime.now(timezone.utc).timestamp()
                    }
                    await self.broadcast_to_room(room, emit_data)
                    self.logging_utility.debug(f"Emitted {len(output)} bytes to room {room}")
        except Exception as e:
            self.logging_utility.error(f"Stream error: {str(e)}", exc_info=True)
        finally:
            if transport and not transport.is_closing():
                transport.close()
            if websocket in self.client_sessions:
                await self.cleanup_session(websocket)

    async def cleanup_session(self, websocket: WebSocket):
        self.logging_utility.info(f"Cleaning up session for connection {websocket}")
        session = self.client_sessions.pop(websocket, None)
        if session:
            try:
                self.logging_utility.debug(f"Terminating process for connection {websocket}")
                session["process"].terminate()
                os.close(session["master_fd"])
                self.logging_utility.info(f"Successfully cleaned up session for connection {websocket}")
            except Exception as e:
                self.logging_utility.error(f"Cleanup error: {str(e)}", exc_info=True)
