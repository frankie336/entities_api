import asyncio
import json
import logging
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
from fastapi import WebSocket, WebSocketDisconnect
from sandbox.services.room_manager import RoomManager

logger = logging.getLogger("shell_session")


class PersistentShellSession:
    def __init__(
        self, websocket: WebSocket, room: str, room_manager: RoomManager, elevated: bool = False
    ):
        """
        Initializes a persistent computer session with optional elevation.

        :param websocket: WebSocket connection
        :param room: Unique identifier for the session room
        :param room_manager: Manages multiple session rooms
        :param elevated: If True, starts the computer with sudo (default: False)
        """
        self.websocket = websocket
        self.room = room
        self.room_manager = room_manager
        self.elevated = elevated
        self.process = None
        self.alive = True
        self.output_task = None

    async def start(self):
        """Starts the persistent computer session, handling incoming WebSocket messages."""
        await self.websocket.accept()
        await self.room_manager.connect(self.room, self.websocket)

        # Choose computer startup command based on elevation flag
        shell_command = ["sudo", "/bin/bash"] if self.elevated else ["/bin/bash"]

        # Start the subprocess
        self.process = await create_subprocess_exec(
            *shell_command, stdin=PIPE, stdout=PIPE, stderr=PIPE
        )

        # Start streaming computer output
        self.output_task = asyncio.create_task(self.stream_output())

        try:
            while self.alive:
                raw_message = await self.websocket.receive_text()
                message = json.loads(raw_message)
                action = message.get("action")

                if action == "shell_command":
                    command = message.get("command", "")
                    await self.send_command(command)

                elif action == "ping":
                    await self.websocket.send_json({"type": "pong"})

                elif action == "disconnect":
                    break  # Explicit disconnect requested

                elif action == "toggle_elevation":
                    self.elevated = not self.elevated  # Toggle elevation setting
                    await self.websocket.send_json(
                        {
                            "type": "status",
                            "content": f"Elevation toggled: {'Enabled' if self.elevated else 'Disabled'}",
                        }
                    )

                else:
                    await self.websocket.send_json(
                        {"type": "error", "content": f"Unknown action: {action}"}
                    )

        except WebSocketDisconnect:
            logger.info(f"Client disconnected from room {self.room}")

        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")

        finally:
            await self.cleanup()

    async def send_command(self, cmd: str):
        """Sends a command to the computer session and broadcasts it."""
        marker = "!__COMMAND_COMPLETE__"
        # Append a marker to know when the command has completed
        full_cmd = f"{cmd}\necho {marker}"

        await self.room_manager.broadcast(
            self.room, {"type": "shell_command", "thread_id": self.room, "content": full_cmd}
        )

        if self.process and self.process.stdin:
            self.process.stdin.write((full_cmd + "\n").encode())
            await self.process.stdin.drain()

    async def stream_output(self):
        """Streams computer output to the WebSocket in real-time."""
        marker = "!__COMMAND_COMPLETE__"
        try:
            while self.alive:
                chunk = await self.process.stdout.read(1024)
                if chunk:
                    text_chunk = chunk.decode(errors="replace")
                    if marker in text_chunk:
                        # Remove the marker from the output before broadcasting
                        text_chunk = text_chunk.replace(marker, "")
                        await self.room_manager.broadcast(
                            self.room,
                            {"type": "shell_output", "thread_id": self.room, "content": text_chunk},
                        )
                        # Send explicit command complete signal
                        await self.room_manager.broadcast(
                            self.room,
                            {"type": "command_complete", "thread_id": self.room, "content": ""},
                        )
                    else:
                        await self.room_manager.broadcast(
                            self.room,
                            {"type": "shell_output", "thread_id": self.room, "content": text_chunk},
                        )
                else:
                    await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.info(f"Streaming cancelled for room {self.room}")

        except Exception as e:
            logger.error(f"Error streaming output: {str(e)}")

    async def cleanup(self):
        """Terminates the computer session and cleans up resources."""
        self.alive = False
        if self.process:
            try:
                self.process.stdin.write(b"exit\n")
                await self.process.stdin.drain()
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except Exception as e:
                logger.error(f"Failed to terminate process: {str(e)}")

        if self.output_task:
            self.output_task.cancel()
            try:
                await self.output_task
            except asyncio.CancelledError:
                pass

        try:
            await self.room_manager.disconnect(self.room, self.websocket)
            await self.websocket.close()
        except Exception as e:
            logger.error(f"Error closing websocket: {str(e)}")

        logger.info(f"Session cleaned up for room {self.room}.")
