# websocket_manager.py
from typing import Dict
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)

    async def send_to_user(self, user_id: str, message: dict) -> bool:
        ws = self.active_connections.get(user_id)
        if not ws:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception:
            # remove dead connection to avoid repeated errors
            self.disconnect(user_id)
            return False

    async def broadcast(self, message: dict):
        # iterate over a copy so we can remove dead connections safely during iteration
        for user_id, ws in list(self.active_connections.items()):
            try:
                await ws.send_json(message)
            except Exception:
                # remove dead connection to avoid repeated errors
                self.disconnect(user_id)

manager = ConnectionManager()
