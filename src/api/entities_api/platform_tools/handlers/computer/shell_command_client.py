#
"""
shell_command_client.py
────────────────────────
WebSocket client that drives the sandbox shell from the orchestration layer.

Key fix over previous version
──────────────────────────────
Commands are now executed SEQUENTIALLY: send one command, wait for the
`command_complete` acknowledgement from the server, then send the next.

The old implementation sent all commands in a tight loop with a 0.1 s sleep
between them.  That was a race condition — a slow shell could still be
processing command N when command N+1 arrived, corrupting execution order
and making sentinel tracking unreliable.
"""
import asyncio
import json
import logging
import os
from typing import AsyncGenerator, List

import websockets
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ShellClient")

SHELL_SERVER_URL = os.getenv("SHELL_SERVER_URL", "ws://localhost:8000/ws/computer")


class ShellClient:
    def __init__(
        self,
        endpoint: str,
        room: str,
        token: str,
        elevated: bool = False,
        timeout: int = 60,
    ):
        self.endpoint = endpoint
        self.room = room
        self.token = token
        self.elevated = elevated
        self.timeout = timeout
        self.ws = None

    async def __aenter__(self) -> "ShellClient":
        conn_str = (
            f"{self.endpoint}"
            f"?room={self.room}"
            f"&elevated={str(self.elevated).lower()}"
            f"&token={self.token}"
        )
        logger.info("Connecting: %s", conn_str)
        self.ws = await websockets.connect(conn_str, ping_interval=self.timeout)
        logger.info("Connected to room '%s'", self.room)
        return self

    async def __aexit__(self, *_) -> None:
        if self.ws:
            try:
                await self.ws.send(json.dumps({"action": "disconnect"}))
            except Exception:
                pass
            await self.ws.close()
            logger.info("WebSocket closed for room '%s'", self.room)

    # ── Core streaming generator ─────────────────────────────────────────

    async def execute_stream(self, commands: List[str]) -> AsyncGenerator[str, None]:
        """
        Executes commands one at a time, yielding output chunks as they arrive.

        Protocol per command:
          1. Send  {"action": "shell_command", "command": <cmd>}
          2. Stream shell_output / shell_error chunks back to caller
          3. Wait for command_complete before sending the next command

        This guarantees ordering and makes the sentinel logic on the server
        side reliable regardless of shell speed.
        """
        if not self.ws:
            raise RuntimeError("WebSocket not connected — use as async context manager.")

        for cmd in commands:
            await self._run_one_command(cmd)
            # _run_one_command is itself an async generator; we need to drive it
            # and yield its output up the call chain.
            # Re-implement as a helper that yields below.

        # (see _execute_stream_impl for the real generator)

    async def _run_one_command(self, cmd: str) -> AsyncGenerator[str, None]:
        """Not used directly — execute_stream is reimplemented below."""
        raise NotImplementedError

    # ── Real async generator ──────────────────────────────────────────────

    async def _stream(self, commands: List[str]) -> AsyncGenerator[str, None]:
        if not self.ws:
            raise RuntimeError("WebSocket not connected.")

        for idx, cmd in enumerate(commands):
            logger.info("Sending command %d/%d: %s", idx + 1, len(commands), cmd)

            await self.ws.send(json.dumps({"action": "shell_command", "command": cmd}))

            # Drain output until command_complete for THIS command
            try:
                async for chunk in self._drain_until_complete():
                    yield chunk
            except Exception as exc:
                logger.error("Error while receiving output for command '%s': %s", cmd, exc)
                yield f"\n[Connection Error: {exc}]\n"
                return

        logger.info("All %d command(s) executed.", len(commands))

    async def _drain_until_complete(self) -> AsyncGenerator[str, None]:
        """Yield output chunks until a command_complete message is received."""
        while True:
            raw = await self.ws.recv()
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type in ("shell_output", "shell_error"):
                content = data.get("content", "")
                if content:
                    logger.debug("Output chunk: %s", content.rstrip())
                    yield content

            elif msg_type == "command_complete":
                logger.info("command_complete received")
                return

            elif msg_type == "pong":
                pass  # heartbeat reply — ignore

            else:
                logger.debug("Unrecognised message: %s", data)

    # ── Public API ────────────────────────────────────────────────────────

    def stream(self, commands: List[str]) -> AsyncGenerator[str, None]:
        """Primary public interface — returns an async generator of output chunks."""
        return self._stream(commands)

    async def execute(self, commands: List[str]) -> str:
        """Convenience wrapper — collects all output into a single string."""
        buf = ""
        async for chunk in self._stream(commands):
            buf += chunk
        return buf


# ── Module-level helpers ──────────────────────────────────────────────────────


async def run_commands(
    commands: List[str],
    room: str,
    token: str,
    elevated: bool = False,
) -> AsyncGenerator[str, None]:
    """Async generator: open a client, stream all commands, close cleanly."""
    async with ShellClient(SHELL_SERVER_URL, room, token, elevated) as client:
        async for chunk in client.stream(commands):
            yield chunk


def run_commands_sync(
    commands: List[str],
    room: str,
    token: str,
    elevated: bool = False,
) -> str:
    """Blocking wrapper for sync call-sites."""

    async def _collect() -> str:
        buf = ""
        async for chunk in run_commands(commands, room, token, elevated):
            buf += chunk
        return buf

    return asyncio.run(_collect())
