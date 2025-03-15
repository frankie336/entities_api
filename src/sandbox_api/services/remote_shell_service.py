import asyncio
import os
import pty
import subprocess
import uuid
from fastapi import WebSocket, WebSocketDisconnect
from src.sandbox_api.services.logging_service import LoggingUtility

class RemoteShellService:
    def __init__(self):
        self.logging_utility = LoggingUtility()
        self.sessions = {}  # Track shell processes and connected clients

    async def start_shell_session(self, websocket: WebSocket, session_id: str = None):
        """Allow multiple clients to join the same shell session."""
        await websocket.accept()

        if session_id and session_id in self.sessions:
            # Existing session: Attach new client
            self.logging_utility.info(f"Client joined existing session {session_id}")
            master_fd = self.sessions[session_id]["master_fd"]
            shell_process = self.sessions[session_id]["process"]
            self.sessions[session_id]["clients"].append(websocket)  # Track clients
        else:
            # New session: Create shell process
            master_fd, slave_fd = pty.openpty()
            session_id = session_id or str(uuid.uuid4())  # Ensure a valid session ID is set

            command = ["firejail", "--quiet", "--private-pty", "--whitelist=/dev/pts", "bash", "-i"]
            shell_process = subprocess.Popen(
                command,
                preexec_fn=os.setsid,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                bufsize=0,
                universal_newlines=True,
            )

            self.sessions[session_id] = {
                "process": shell_process,
                "master_fd": master_fd,
                "clients": [websocket],  # Track connected clients
                "history": []  # Store command outputs
            }
            os.close(slave_fd)

            self.logging_utility.info(f"New session created: {session_id}")

            # Execute predefined startup commands
            startup_commands = [
                "echo 'Welcome to your sandboxed shell!'",
                "whoami",
                "pwd",
                "ls -lah"
            ]

            for cmd in startup_commands:
                os.write(master_fd, cmd.encode() + b"\n")

        # Send session ID to client (ensure consistency)
        await websocket.send_text(f"SESSION_ID:{session_id}")

        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.connect_read_pipe(lambda: protocol, os.fdopen(master_fd, 'rb'))

        async def read_from_shell():
            """Broadcast shell output to all connected clients."""
            try:
                while not reader.at_eof():
                    data = await reader.read(1024)  # You can adjust buffer size if needed
                    if data:
                        text = data.decode(errors="ignore")
                        # Store history so new clients see prior output
                        self.sessions[session_id]["history"].append(text)
                        for client in self.sessions[session_id]["clients"]:
                            await client.send_text(text)
            except ConnectionResetError:
                pass

        read_task = asyncio.create_task(read_from_shell())

        # Send command history to new client
        for previous_output in self.sessions[session_id]["history"]:
            await websocket.send_text(previous_output)

        try:
            while True:
                message = await websocket.receive_text()
                if message.startswith("SESSION_ID:"):
                    continue  # Prevent session ID from being executed
                await loop.run_in_executor(None, lambda: os.write(master_fd, message.encode() + b"\n"))
        except WebSocketDisconnect:
            self.sessions[session_id]["clients"].remove(websocket)
            self.logging_utility.info(f"Client disconnected from session {session_id}")

            # If no clients remain, clean up the session
            if not self.sessions[session_id]["clients"]:
                self.logging_utility.info(f"Session {session_id} has no active clients. Terminating shell.")
                shell_process.terminate()
                del self.sessions[session_id]
        finally:
            read_task.cancel()
            transport.close()
