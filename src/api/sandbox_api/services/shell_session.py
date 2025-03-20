import asyncio
import json
import logging
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
from fastapi import WebSocket, WebSocketDisconnect
from sandbox_api.services.room_manager import RoomManager

logger = logging.getLogger("shell_session")


class PersistentShellSession:
    def __init__(self, websocket: WebSocket, room: str, room_manager: RoomManager):
        self.websocket = websocket
        self.room = room
        self.room_manager = room_manager
        self.process = None
        self.alive = True
        self.output_task = None

    async def start(self):
        await self.websocket.accept()
        await self.room_manager.connect(self.room, self.websocket)

        # Start explicitly persistent shell subprocess
        self.process = await create_subprocess_exec(
            '/bin/bash',
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE
        )

        # Directly and explicitly stream shell outputs immediately
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
                    break   # explicit disconnect requested

                else:
                    await self.websocket.send_json({
                        "type": "error",
                        "content": f"Unknown action: {action}"
                    })

        except WebSocketDisconnect:
            logger.info(f"Client explicitly disconnected from room {self.room}")

        except Exception as e:
            logger.error(f"Unexpected explicit error: {str(e)}")

        finally:
            await self.cleanup()

    # Explicitly updated send_command method that clearly broadcasts the command itself first
    async def send_command(self, cmd: str):
        # First, explicitly broadcast the issued command to all participants
        await self.room_manager.broadcast(self.room, {
            "type": "shell_command",
            "thread_id": self.room,
            "content": cmd
        })

        # Now send the command explicitly to the shell subprocess
        if self.process and self.process.stdin:
            self.process.stdin.write((cmd + '\n').encode())
            await self.process.stdin.drain()

    # Clearly-defined streaming output method
    async def stream_output(self):
        try:
            while self.alive:
                chunk = await self.process.stdout.read(1024)
                if chunk:
                    # Stream explicit shell output clearly back to clients
                    await self.room_manager.broadcast(self.room, {
                        "type": "shell_output",
                        "thread_id": self.room,
                        "content": chunk.decode(errors='replace')
                    })
                else:
                    await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.info(f"Streaming explicitly cancelled for room {self.room}")

        except Exception as e:
            logger.error(f"Error explicitly streaming output: {str(e)}")

    # Explicit, clear cleanup/shutdown
    async def cleanup(self):
        self.alive = False
        if self.process:
            try:
                # Attempt explicit graceful exit of shell
                self.process.stdin.write(b'exit\n')
                await self.process.stdin.drain()
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except Exception as e:
                logger.error(f"Cleanup explicitly failed to terminate process: {str(e)}")

        # Properly stopping the output streamer
        if self.output_task:
            self.output_task.cancel()
            try:
                await self.output_task
            except asyncio.CancelledError:
                pass

        try:
            # Explicit disconnect & close websocket
            await self.room_manager.disconnect(self.room, self.websocket)
            await self.websocket.close()
        except Exception as e:
            logger.error(f"Explicit error closing websocket during cleanup: {str(e)}")

        logger.info(f"Explicit session cleaned up clearly for room {self.room}.")