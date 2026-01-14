from typing import Dict
from fastapi import WebSocket
from supabase_client import supabase

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

    async def flush_pending(self, user_id: str):
        """Send any queued notifications for user_id stored in `pending_notifications` table."""
        ws = self.active_connections.get(user_id)
        if not ws:
            return
        try:
            res = supabase.table("pending_notifications").select("*").eq("user_id", user_id).execute()
            pending = res.data or []
        except Exception:
            print(f"Warning: failed to read pending_notifications for {user_id}")
            return

        for item in pending:
            payload = item.get("payload") if isinstance(item, dict) else item
            try:
                await ws.send_json(payload)
                # delete pending notification after successful send
                try:
                    supabase.table("pending_notifications").delete().eq("id", item.get("id")).execute()
                except Exception:
                    print("Warning: failed to delete pending notification", item.get("id"))
            except Exception:
                print(f"Warning: failed to send queued notification to {user_id}")
                # keep pending if send failed

manager = ConnectionManager()
