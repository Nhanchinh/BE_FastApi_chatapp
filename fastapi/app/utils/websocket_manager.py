from typing import Dict, List

from fastapi import WebSocket


class ConnectionManager:

    def __init__(self) -> None:
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        if user_id in self.active_connections:
            try:
                self.active_connections[user_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, receiver_id: str, message: str) -> None:
        if receiver_id in self.active_connections:
            for conn in list(self.active_connections[receiver_id]):
                await conn.send_text(message)


