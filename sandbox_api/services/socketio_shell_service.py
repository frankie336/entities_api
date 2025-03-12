import asyncio
import json
import os
from datetime import datetime

from engineio import AsyncServer


class SocketIOShellService:
    def __init__(self, sio: AsyncServer):
        self.sio = sio
        self.client_sessions = {}  # Track individual client sessions
        self.rooms = {}  # Track rooms and their clients
        self._register_handlers()

    def _register_handlers(self):
        """Simplified handler registration"""
        namespace = '/shell'

        @self.sio.on('connect', namespace=namespace)
        async def handle_connect(sid, environ, auth):
            """Handle new connection with immediate shell creation."""
            logger.info(f"New connection from {sid}")
            try:
                user_id = auth.get("user_id", "anonymous")
                room_name = f"shell_{user_id}"  # Dynamic room naming
                self._add_to_room(room_name, sid)  # Add client to the room

                # Delegate shell session handling
                await self._create_client_session(sid)

                # Broadcast that the shell session started
                await self._broadcast_to_room(room_name, f"User {user_id} started a shell session.", sid)
            except Exception as e:
                logger.error(f"Error during connection: {str(e)}")
                await self.sio.disconnect(sid)

        @self.sio.on('shell_command', namespace=namespace)
        async def handle_command(sid, command):
            """Handle direct command execution."""
            await self._process_command(sid, command)

        @self.sio.on('disconnect', namespace=namespace)
        async def handle_disconnect(sid):
            """Guaranteed cleanup on disconnect."""
            await self._cleanup_session(sid)
            self._remove_from_room(sid)  # Remove client from room

    def _add_to_room(self, room_name: str, sid: str):
        """Add a client to a room."""
        if room_name not in self.rooms:
            self.rooms[room_name] = set()
        self.rooms[room_name].add(sid)
        logger.info(f"Added {sid} to room {room_name}")

    def _remove_from_room(self, sid: str):
        """Remove a client from all rooms."""
        for room_name, clients in self.rooms.items():
            if sid in clients:
                clients.remove(sid)
                logger.info(f"Removed {sid} from room {room_name}")
                if not clients:
                    del self.rooms[room_name]
                    logger.info(f"Room {room_name} is empty and has been deleted")

    async def _broadcast_to_room(self, room_name: str, message: str, exclude_sid: str = None):
        """Broadcast a message to all clients in a room, excluding a specific client."""
        if room_name in self.rooms:
            for sid in self.rooms[room_name]:
                if sid != exclude_sid:
                    await self.sio.emit('broadcast_message', {'message': message}, to=sid)
            logger.info(f"Broadcasted message to room {room_name}")

    async def _create_client_session(self, sid):
        """Create isolated shell session per client."""
        master_fd, slave_fd = pty.openpty()

        try:
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
            logger.error(f"Process creation failed: {str(e)}")
            await self.sio.disconnect(sid)
            return

        self.client_sessions[sid] = {
            "process": proc,
            "master_fd": master_fd,
            "created_at": datetime.utcnow()
        }

        os.close(slave_fd)
        asyncio.create_task(self._stream_output(sid))
        logger.info(f"Created shell session for {sid}")

    async def _process_command(self, sid, command):
        """Execute command in client-specific shell."""
        session = self.client_sessions.get(sid)
        if not session or session["process"].poll() is not None:
            logger.warning(f"Invalid session for {sid}")
            await self.sio.emit('error', {'message': 'Session not active'}, to=sid)
            return

        try:
            os.write(session['master_fd'], f"{command}\n".encode())
            logger.debug(f"Executed command for {sid}: {command[:50]}...")
        except OSError as e:
            logger.error(f"Command write failed for {sid}: {str(e)}")
            await self._cleanup_session(sid)

    async def _stream_output(self, sid):
        """Direct output streaming to client."""
        session = self.client_sessions.get(sid)
        if not session:
            return

        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()

        try:
            transport, _ = await loop.connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(reader),
                os.fdopen(session['master_fd'], 'rb')
            )

            while not reader.at_eof():
                data = await reader.read(4096)
                if data:
                    output = data.decode(errors='ignore')
                    await self.sio.emit(
                        'shell_output',
                        {
                            'data': json.dumps({'type': 'hot_shell', 'content': output}),
                            'timestamp': datetime.utcnow().isoformat()
                        },
                        to=sid
                    )
        finally:
            transport.close()
            await self._cleanup_session(sid)

    async def _cleanup_session(self, sid):
        """Guaranteed resource cleanup."""
        session = self.client_sessions.pop(sid, None)
        if session:
            try:
                session["process"].terminate()
                os.close(session["master_fd"])
                logger.info(f"Cleaned up session for {sid}")
            except Exception as e:
                logger.error(f"Cleanup error for {sid}: {str(e)}")