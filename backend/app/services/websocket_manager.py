import asyncio
from fastapi import WebSocket

class WebSocketManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            peers = list(self._connections)
        dead = []
        for peer in peers:
            try:
                await peer.send_json(message)
            except Exception:
                dead.append(peer)
        if dead:
            async with self._lock:
                for peer in dead:
                    self._connections.discard(peer)

manager = WebSocketManager()
