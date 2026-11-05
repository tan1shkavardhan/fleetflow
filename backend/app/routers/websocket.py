from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from Backend.app.services.websocket_manager import manager

router = APIRouter(tags=["realtime"])

@router.websocket("/ws/vehicles")
async def vehicle_events(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "connection_status", "status": "connected"})
        while True:
            # Client may send ping messages; no client command mutates server state.
            message = await websocket.receive_text()
            if message.strip().lower() in {"ping", "\"ping\""}:
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
