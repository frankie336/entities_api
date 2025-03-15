import asyncio
import json
import os
import pty
import signal
from datetime import datetime, timezone
from typing import Dict, Set, List

import redis
from fastapi import WebSocket, WebSocketDisconnect
from src.sandbox_api.services.logging_service import LoggingUtility

# Redis setup
redis_client = redis.StrictRedis(host='redis_server', port=6379, db=0, decode_responses=True)

logging_utility = LoggingUtility()


class WebSocketShellService:
    def __init__(self):
        self.client_sessions: Dict[WebSocket, dict] = {}
        self.rooms: Dict[str, Set[WebSocket]] = {}
        # Track tasks spawned per session so they can be cancelled on cleanup.
        self.tasks: Dict[WebSocket, List[asyncio.Task]] = {}
        self.cleanup_lock = asyncio.Lock()  # Lock to serialize cleanup calls.
        self.logging_utility = LoggingUtility()
        self.namespace = "/shell"
        self.logging_utility.info(f"WebSocket Shell Service initialized on namespace: {self.namespace}")

    # --- Session Persistence ---
    def store_session_in_redis(self, websocket: WebSocket, session_data: dict):
        session_id = str(websocket.client)
        redis_client.set(
            f"session:{session_id}",
            json.dumps({
                "created_at": session_data["created_at"],
                "thread_id": next((k for k, v in self.rooms.items() if websocket in v), None)
            })
        )
        redis_client.expire(f"session:{session_id}", 3600)

    def retrieve_session_from_redis(self, websocket: WebSocket):
        session_id = str(websocket.client)
        session_data = redis_client.get(f"session:{session_id}")
        return json.loads(session_data) if session_data else None

    def delete_session_from_redis(self, websocket: WebSocket):
        redis_client.delete(f"session:{str(websocket.client)}")

    # --- Room Management ---
    def add_to_room(self, room_name: str, websocket: WebSocket):
        if room_name not in self.rooms:
            self.rooms[room_name] = set()
        self.rooms[room_name].add(websocket)
        self.logging_utility.info(f"Client joined room '{room_name}'")

    def remove_from_room(self, websocket: WebSocket):
        for room_name, clients in list(self.rooms.items()):
            if websocket in clients:
                clients.remove(websocket)
                if not clients:
                    del self.rooms[room_name]

    async def broadcast_to_room(self, room_name: str, message: dict, sender: WebSocket = None):
        if room_name not in self.rooms:
            return
        full_message = {
            **message,
            "thread_id": room_name,
            "timestamp": datetime.now(timezone.utc).timestamp()
        }
        for client in set(self.rooms[room_name]):
            if client != sender:  # Exclude the sending client
                try:
                    await client.send_text(json.dumps(full_message))
                except Exception as e:
                    self.logging_utility.error(f"Failed to send to {client}: {str(e)}")
                    await self.cleanup_session(client)

    # --- Shell Session Management ---
    async def create_client_session(self, websocket: WebSocket):
        try:
            master_fd, slave_fd = pty.openpty()
            proc = await asyncio.create_subprocess_exec(
                "bash", "-i",
                preexec_fn=os.setsid,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd
            )
            os.close(slave_fd)

            session_data = {
                "process": proc,
                "master_fd": master_fd,
                "created_at": datetime.utcnow().isoformat(),
            }
            self.client_sessions[websocket] = session_data
            self.store_session_in_redis(websocket, session_data)

            # Create tasks for streaming output and heartbeat.
            task_stream = asyncio.create_task(self.stream_output(websocket))
            task_hb = asyncio.create_task(self.heartbeat(websocket))
            self.tasks[websocket] = [task_stream, task_hb]

        except Exception as e:
            self.logging_utility.error(f"Process creation failed: {str(e)}")
            await websocket.close()

    async def process_command(self, websocket: WebSocket, command: str):
        session = self.client_sessions.get(websocket)
        if session and session["process"].returncode is None:
            try:
                os.write(session['master_fd'], f"{command}\n".encode())
            except OSError as e:
                self.logging_utility.error(f"Write error: {str(e)}")

    async def stream_output(self, websocket: WebSocket):
        session = self.client_sessions.get(websocket)
        if not session:
            return

        reader = asyncio.StreamReader()
        transport = None  # Initialize transport to None
        try:
            # Duplicate the master_fd so the original is not closed by fdopen.
            dup_fd = os.dup(session['master_fd'])
            f_pipe = os.fdopen(dup_fd, 'rb')
            try:
                transport, _ = await asyncio.get_event_loop().connect_read_pipe(
                    lambda: asyncio.StreamReaderProtocol(reader),
                    f_pipe
                )
            except FileExistsError as fee:
                self.logging_utility.error("FileExistsError in connect_read_pipe (first attempt): %s", fee)
                await asyncio.sleep(0.1)
                # Retry with a fresh duplicate.
                dup_fd = os.dup(session['master_fd'])
                f_pipe = os.fdopen(dup_fd, 'rb')
                transport, _ = await asyncio.get_event_loop().connect_read_pipe(
                    lambda: asyncio.StreamReaderProtocol(reader),
                    f_pipe
                )

            while not reader.at_eof():
                data = await reader.read(4096)
                if data:
                    room = next((r for r, clients in self.rooms.items() if websocket in clients), None)
                    if room:
                        await self.broadcast_to_room(room, {
                            "content": data.decode(errors='ignore'),
                            "type": "shell_output"
                        })
        finally:
            if transport:
                transport.close()
            await self.cleanup_session(websocket)

    async def heartbeat(self, websocket: WebSocket):
        try:
            while websocket in self.client_sessions:
                await asyncio.sleep(10)
                try:
                    await websocket.send_text(json.dumps({
                        "action": "ping",
                        "thread_id": next((k for k, v in self.rooms.items() if websocket in v), None),
                        "timestamp": datetime.now(timezone.utc).timestamp()
                    }))
                except Exception as e:
                    break
        finally:
            await self.cleanup_session(websocket)

    async def cancel_task(self, task: asyncio.Task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def cleanup_session(self, websocket: WebSocket):
        async with self.cleanup_lock:
            # If session is already cleaned up, return immediately.
            if websocket not in self.client_sessions:
                return

            # Cancel any pending tasks.
            if websocket in self.tasks:
                tasks = self.tasks.pop(websocket)
                await asyncio.gather(*[self.cancel_task(task) for task in tasks], return_exceptions=True)

            # Remove the session if it exists.
            if websocket in self.client_sessions:
                session = self.client_sessions.pop(websocket)
                try:
                    os.killpg(os.getpgid(session["process"].pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.close(session["master_fd"])
                except OSError as e:
                    if e.errno != 9:  # Ignore "Bad file descriptor"
                        raise
                self.delete_session_from_redis(websocket)

            self.remove_from_room(websocket)
            self.logging_utility.info("Cleanup complete for websocket: {}".format(websocket.client))

    async def handle_websocket(self, websocket: WebSocket):
        await websocket.accept()
        current_room = None

        try:
            session_data = self.retrieve_session_from_redis(websocket)
            if session_data:
                self.client_sessions[websocket] = session_data
                current_room = session_data.get("thread_id")
                if current_room:
                    self.add_to_room(current_room, websocket)
            else:
                await self.create_client_session(websocket)

            while True:
                data = await websocket.receive_text()
                payload = json.loads(data)

                if (action := payload.get("action")) == "join_room":
                    if (room := payload.get("room")) and room != current_room:
                        current_room = room
                        self.add_to_room(room, websocket)
                elif action == "shell_command":
                    if command := payload.get("command", "").strip():
                        await self.process_command(websocket, command)
                elif action == "terminate_session":
                    await self.cleanup_session(websocket)
                elif action == "message":
                    if current_room and (message := payload.get("message")):
                        await self.broadcast_to_room(current_room, {
                            "content": message,
                            "type": "chat_message",
                            "sender": payload.get("sender")
                        })

        except WebSocketDisconnect:
            self.logging_utility.info("Client disconnected")
        except Exception as e:
            self.logging_utility.error(f"WebSocket error: {str(e)}")
        finally:
            await self.cleanup_session(websocket)
