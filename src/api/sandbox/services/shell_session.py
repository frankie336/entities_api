import asyncio
import json
import logging
import os
import pty
import subprocess
import termios  # <--- REQUIRED for controlling the terminal echo
from fastapi import WebSocket, WebSocketDisconnect
from sandbox.services.room_manager import RoomManager

logger = logging.getLogger("shell_session")


class PersistentShellSession:
    # A magic string to let us know the shell finished the previous command
    CMD_SENTINEL = "###__CMD_COMPLETE__###"

    def __init__(
        self,
        websocket: WebSocket,
        room: str,
        room_manager: RoomManager,
        elevated: bool = False,
    ):
        self.websocket = websocket
        self.room = room
        self.room_manager = room_manager
        self.elevated = elevated

        self.process = None
        self.master_fd = None
        self.alive = True

    async def start(self):
        # NOTE: If your Router (v1.py) accepts the socket, keep this commented.
        # await self.websocket.accept()

        await self.room_manager.connect(self.room, self.websocket)

        # 1. Create PTY
        self.master_fd, slave_fd = pty.openpty()

        # ------------------------------------------------------------------
        # TRICK: Disable the PTY's native echo.
        # This hides the "whoami; echo SENTINEL" text from appearing automatically.
        # We will manually broadcast the clean "whoami" later.
        # ------------------------------------------------------------------
        try:
            attrs = termios.tcgetattr(slave_fd)
            attrs[3] = attrs[3] & ~termios.ECHO  # Turn off ECHO flag
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
        except Exception as e:
            logger.warning(f"Failed to disable PTY echo: {e}")

        shell_command = ["sudo", "/bin/bash"] if self.elevated else ["/bin/bash"]

        try:
            # 2. Start Subprocess
            self.process = subprocess.Popen(
                shell_command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid,
                shell=False,
                close_fds=True,
            )
            os.close(slave_fd)

            # 3. Register Reader
            loop = asyncio.get_running_loop()
            loop.add_reader(self.master_fd, self._read_output)

            # 4. Listen for WebSocket messages
            while self.alive:
                raw_message = await self.websocket.receive_text()
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue

                action = message.get("action")

                if action == "shell_command":
                    command = message.get("command", "")
                    await self.send_command(command)

                elif action == "ping":
                    await self.websocket.send_json({"type": "pong"})

                elif action == "disconnect":
                    break

                elif action == "toggle_elevation":
                    self.elevated = not self.elevated
                    await self.websocket.send_json(
                        {
                            "type": "status",
                            "content": f"Elevation flag changed to: {self.elevated}",
                        }
                    )
                else:
                    await self.websocket.send_json(
                        {"type": "error", "content": f"Unknown action: {action}"}
                    )

        except WebSocketDisconnect:
            logger.info(f"Client disconnected from room {self.room}")
        except Exception as e:
            logger.error(f"Unexpected error in shell session: {str(e)}")
        finally:
            await self.cleanup()

    def _read_output(self):
        """Reads from PTY, detects sentinel, and broadcasts."""
        try:
            if not self.master_fd:
                return

            output = os.read(self.master_fd, 4096)

            if output:
                text_chunk = output.decode("utf-8", errors="replace")

                # --- SENTINEL DETECTION LOGIC ---
                completion_detected = False

                if self.CMD_SENTINEL in text_chunk:
                    completion_detected = True
                    # Clean the sentinel from the output so the user doesn't see it
                    text_chunk = text_chunk.replace(self.CMD_SENTINEL, "")
                    # Often the sentinel leaves a trailing newline or prompt artifact
                    text_chunk = text_chunk.replace("\n\r\n", "\n")

                if text_chunk:
                    asyncio.create_task(
                        self.room_manager.broadcast(
                            self.room,
                            {
                                "type": "shell_output",
                                "thread_id": self.room,
                                "content": text_chunk,
                            },
                        )
                    )

                if completion_detected:
                    logger.info(f"Command completion detected in room {self.room}")
                    asyncio.create_task(
                        self.room_manager.broadcast(
                            self.room, {"type": "command_complete"}
                        )
                    )
            else:
                self.alive = False
        except OSError:
            self.alive = False

    async def send_command(self, cmd: str):
        """
        Injects the command, manually echoes the clean version,
        and then runs the sentinel version in the background.
        """
        if self.master_fd and self.alive:
            try:
                # 1. VISUAL ECHO: Manually send the CLEAN command to the UI
                # This makes it look like the user typed it.
                # Adding \r\n simulates the user hitting Enter.
                asyncio.create_task(
                    self.room_manager.broadcast(
                        self.room,
                        {
                            "type": "shell_output",
                            "thread_id": self.room,
                            "content": f"{cmd}\r\n",
                        },
                    )
                )

                # 2. ACTUAL EXECUTION: Run the command + Sentinel
                # The PTY will NOT echo this back because we disabled termios.ECHO
                wrapped_cmd = f"{cmd}; echo '{self.CMD_SENTINEL}'\n"
                os.write(self.master_fd, wrapped_cmd.encode())

            except OSError as e:
                logger.error(f"Failed to write to PTY: {e}")
                self.alive = False

    async def cleanup(self):
        self.alive = False
        loop = asyncio.get_running_loop()

        if self.master_fd:
            try:
                loop.remove_reader(self.master_fd)
                os.close(self.master_fd)
            except Exception:
                pass
            self.master_fd = None

        if self.process:
            try:
                self.process.terminate()
                self.process.wait()
            except Exception:
                pass

        try:
            await self.room_manager.disconnect(self.room, self.websocket)
            await self.websocket.close()
        except Exception:
            pass
