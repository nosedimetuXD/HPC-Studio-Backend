"""WebSocket route for bidirectional events and state streaming."""

import json
import logging
import time
from typing import Any, Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from hpc_studio.server.auth import verify_ws_token
from hpc_studio.server.config import ServerConfig
from hpc_studio.server.event_manager import ConnectionManager

logger = logging.getLogger("hpc_studio.server.ws")


def create_events_router(config: ServerConfig, event_manager: ConnectionManager) -> APIRouter:
    """Create WebSocket events router with injected config and connection manager."""
    r = APIRouter()

    @r.websocket("/ws/events")
    async def websocket_events_endpoint(websocket: WebSocket):
        """Bidirectional WebSocket endpoint for system events and state streaming."""
        # Authenticate incoming WebSocket connection
        if not verify_ws_token(websocket, config.token):
            logger.warning("Rejected unauthorized WebSocket connection attempt.")
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Unauthorized: Invalid or missing token",
            )
            return

        await event_manager.connect(websocket)

        # Send initial connected handshake message
        await event_manager.send_personal_message(
            {
                "type": "system:connected",
                "payload": {
                    "message": "Connected to HPC Studio Event Stream",
                    "version": config.version,
                    "server_time": time.time(),
                },
                "timestamp": time.time(),
            },
            websocket,
        )

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    message: Dict[str, Any] = json.loads(data)
                except Exception:
                    await event_manager.send_personal_message(
                        {
                            "type": "error",
                            "payload": {"message": "Invalid JSON format"},
                            "timestamp": time.time(),
                        },
                        websocket,
                    )
                    continue

                msg_type = message.get("type", "unknown")
                payload = message.get("payload", {})

                if msg_type == "ping":
                    await event_manager.send_personal_message(
                        {
                            "type": "pong",
                            "payload": {
                                "client_timestamp": payload.get("timestamp"),
                                "server_timestamp": time.time(),
                            },
                            "timestamp": time.time(),
                        },
                        websocket,
                    )
                elif msg_type == "broadcast":
                    # Broadcast to other clients
                    event_name = payload.get("event", "custom_event")
                    event_data = payload.get("data", {})
                    await event_manager.broadcast(event_name, event_data)
                else:
                    # Generic message acknowledgement or custom handler
                    await event_manager.send_personal_message(
                        {
                            "type": "ack",
                            "payload": {
                                "received_type": msg_type,
                                "timestamp": time.time(),
                            },
                            "timestamp": time.time(),
                        },
                        websocket,
                    )

        except WebSocketDisconnect:
            await event_manager.disconnect(websocket)
        except Exception as e:
            logger.error("Unexpected error in WebSocket loop: %s", e)
            await event_manager.disconnect(websocket)

    return r
