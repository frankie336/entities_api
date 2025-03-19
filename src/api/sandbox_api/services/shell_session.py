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
            stdin=PIPE, stdout=PIPE, stderr=PIPE
        )

        # Explicitly directly stream shell outputs immediately
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
                    break
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

    async def send_command(self, cmd: str):
        if self.process and self.process.stdin:
            self.process.stdin.write((cmd + '\n').encode())
            await self.process.stdin.drain()

    # *** THIS IS THE CRUCIAL CLEARLY UPDATED METHOD: ***
    async def stream_output(self):
        try:
            while self.alive:
                chunk = await self.process.stdout.read(1024)  # explicitly read small bytes immediately
                if chunk:
                    await self.room_manager.broadcast(self.room, {
                        "type": "shell_output",
                        "thread_id": self.room,  # explicitly include room/thread_id clearly
                        "content": chunk.decode(errors='replace')  # immediately decode safely
                    })
                else:
                    await asyncio.sleep(0.01)  # explicitly pause momentarily if no outputs
        except asyncio.CancelledError:
            logger.info(f"Streaming cancelled explicitly for room {self.room}")

        except Exception as e:
            logger.error(f"Error explicitly streaming output: {str(e)}")

    async def cleanup(self):
        self.alive = False

        # clean shutdown explicitly
        if self.process:
            try:
                self.process.stdin.write(b'exit\n')
                await self.process.stdin.drain()
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except Exception as e:
                logger.error(f"Cleanup explicitly failed to terminate process: {str(e)}")

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
            logger.error(f"Explicitly error closing websocket during cleanup: {str(e)}")

        logger.info(f"Explicit Session cleaned up clearly for room {self.room}.")