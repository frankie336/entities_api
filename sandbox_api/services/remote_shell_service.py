# sandbox_api/services/remote_shell_service.py
import asyncio
import os
import pty
import subprocess
from fastapi import WebSocket, WebSocketDisconnect
from sandbox_api.services.logging_service import LoggingUtility


class RemoteShellService:
    def __init__(self):
        self.logging_utility = LoggingUtility()

    async def start_shell_session(self, websocket: WebSocket):
        """Robust shell session handler with proper async I/O"""
        await websocket.accept()
        master_fd, slave_fd = pty.openpty()
        shell_process = None

        try:
            # 1. Configure firejail with PTY access
            command = [
                "firejail",
                "--quiet",
                "--private-pty",  # Critical for PTY access
                "--whitelist=/dev/pts",
                "bash", "-i"
            ]

            shell_process = subprocess.Popen(
                command,
                preexec_fn=os.setsid,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                bufsize=0,
                universal_newlines=True,
            )

            # 2. Terminal initialization sequence
            def init_terminal():
                os.write(master_fd, b"export TERM=xterm-256color\n")
                os.write(master_fd, b"stty sane\n")
                os.write(master_fd, b"unset PROMPT_COMMAND\n")
                os.write(master_fd, b"PS1='$ '\n")  # Simple prompt

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, init_terminal)

            # 3. Non-blocking I/O setup
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await loop.connect_read_pipe(
                lambda: protocol, os.fdopen(master_fd, 'rb')
            )

            async def read_from_shell():
                """Async stream reader with proper flow control"""
                try:
                    while not reader.at_eof():
                        data = await reader.read(1024)
                        if data:
                            self.logging_utility.debug(f"Sent {len(data)} bytes")
                            await websocket.send_text(data.decode(errors="ignore"))
                except ConnectionResetError:
                    pass

            read_task = asyncio.create_task(read_from_shell())

            # 4. Input handling with echo control
            try:
                while True:
                    message = await websocket.receive_text()
                    self.logging_utility.debug(f"Received: {message.strip()}")

                    # Write with explicit newline and flush
                    await loop.run_in_executor(
                        None,
                        lambda: os.write(master_fd, message.encode() + b"\n")
                    )

            except WebSocketDisconnect:
                self.logging_utility.info("Client disconnected normally")
            finally:
                read_task.cancel()
                transport.close()
                os.close(master_fd)
                os.close(slave_fd)
                if shell_process:
                    shell_process.terminate()
                    try:
                        shell_process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        shell_process.kill()

        except Exception as e:
            self.logging_utility.error(f"Shell session failed: {str(e)}")
            await websocket.close(code=1011)