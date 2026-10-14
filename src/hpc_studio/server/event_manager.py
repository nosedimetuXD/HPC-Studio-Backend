"""WebSocket connection and event management for HPC Studio server."""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Set
from fastapi import WebSocket

logger = logging.getLogger("hpc_studio.server.events")


class ConnectionManager:
    """Manages active WebSocket connections and bidirectional event broadcasting."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info("WebSocket client connected. Active connections: %d", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket connection."""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info("WebSocket client disconnected. Active connections: %d", len(self.active_connections))

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket) -> None:
        """Send a JSON payload to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.warning("Error sending message to client: %s", e)
            await self.disconnect(websocket)

    async def broadcast(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Broadcast an event to all connected clients."""
        message = {
            "type": event_type,
            "payload": payload or {},
            "timestamp": time.time(),
        }
        async with self._lock:
            dead_connections = []
            for connection in list(self.active_connections):
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.warning("Failed to broadcast to connection: %s", e)
                    dead_connections.append(connection)

            for dead in dead_connections:
                self.active_connections.discard(dead)

    @property
    def client_count(self) -> int:
        """Return total active WebSocket clients."""
        return len(self.active_connections)
