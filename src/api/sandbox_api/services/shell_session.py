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

        # start a persistent shell session
        self.process = await create_subprocess_exec(
            '/bin/bash',
            stdin=PIPE, stdout=PIPE, stderr=PIPE
        )

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
            logger.info(f"Client disconnected from room {self.room}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
        finally:
            await self.cleanup()

    async def send_command(self, cmd: str):
        if self.process and self.process.stdin:
            self.process.stdin.write((cmd + '\n').encode())
            await self.process.stdin.drain()

    async def stream_output(self):
        try:
            while self.alive:
                line = await self.process.stdout.readline()
                if line:
                    content = line.decode()
                    await self.room_manager.broadcast(self.room, {
                        "type": "shell_output",
                        "thread_id": self.room,
                        "content": content
                    })
                else:
                    await asyncio.sleep(0.1)  # Wait explicitly briefly instead of breaking
        except asyncio.CancelledError:
            logger.info(f"Streaming explicitly cancelled for room {self.room}")
        except Exception as e:
            logger.error(f"Error explicitly streaming output: {str(e)}")

    async def cleanup(self):
        self.alive = False
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
            logger.error(f"Cleanup explicitly failed websocket close: {str(e)}")

        logger.info(f"Session explicitly cleaned up for room {self.room}.")