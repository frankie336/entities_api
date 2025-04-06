from typing import Dict, Set
from fastapi import WebSocket
import asyncio
import json


class RoomManager:
    def __init__(self):
        self.connections: Dict[str, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, room: str, websocket: WebSocket):
        async with self.lock:
            if room not in self.connections:
                self.connections[room] = set()
            self.connections[room].add(websocket)

    async def disconnect(self, room: str, websocket: WebSocket):
        async with self.lock:
            if room in self.connections:
                self.connections[room].discard(websocket)
                if not self.connections[room]:
                    del self.connections[room]

    async def broadcast(self, room: str, message: dict):
        async with self.lock:
            websockets = self.connections.get(room, set()).copy()

        send_coros = [
            ws.send_json(message) for ws in websockets if ws.client_state.name == "CONNECTED"
        ]

        await asyncio.gather(*send_coros, return_exceptions=True)
