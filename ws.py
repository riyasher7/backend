from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websocket_manager import manager

router = APIRouter()

@router.websocket("/ws/notifications/{user_id}")
async def notifications_ws(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    # flush queued notifications (best-effort)
    try:
        await manager.flush_pending(user_id)
    except Exception:
        print(f"Warning: failed to flush pending notifications for {user_id}")

    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id)

