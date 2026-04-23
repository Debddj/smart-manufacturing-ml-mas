"""
api/websocket_hub.py — WebSocket hub for real-time inventory updates.

Broadcasts inventory changes (from sales, restocking, transfers)
to all connected store managers instantly.
"""

from __future__ import annotations

import json
from typing import Dict, List, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class InventoryWebSocketHub:
    """
    Manages WebSocket connections and broadcasts inventory updates.

    Connections are stored per-store so that updates can be targeted
    to relevant store managers.
    """

    def __init__(self):
        # All active connections
        self._connections: List[WebSocket] = []
        # Map store_id → set of connections (for targeted broadcasts)
        self._store_connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, store_id: int = None):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        if store_id:
            if store_id not in self._store_connections:
                self._store_connections[store_id] = set()
            self._store_connections[store_id].add(websocket)

    def disconnect(self, websocket: WebSocket, store_id: int = None):
        """Remove a WebSocket connection."""
        if websocket in self._connections:
            self._connections.remove(websocket)
        if store_id and store_id in self._store_connections:
            self._store_connections[store_id].discard(websocket)

    async def broadcast(self, message: dict):
        """Broadcast a message to ALL connected clients."""
        data = json.dumps(message)
        dead = []
        for conn in self._connections:
            try:
                await conn.send_text(data)
            except Exception:
                dead.append(conn)
        # Clean up dead connections
        for conn in dead:
            if conn in self._connections:
                self._connections.remove(conn)

    async def broadcast_to_store(self, store_id: int, message: dict):
        """Broadcast a message to clients connected for a specific store."""
        conns = self._store_connections.get(store_id, set())
        if not conns:
            return
        data = json.dumps(message)
        dead = []
        for conn in conns:
            try:
                await conn.send_text(data)
            except Exception:
                dead.append(conn)
        for conn in dead:
            conns.discard(conn)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# ── Global hub instance ───────────────────────────────────────────────────────
hub = InventoryWebSocketHub()


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/inventory")
async def inventory_websocket(websocket: WebSocket, store_id: int = None):
    """
    WebSocket endpoint for real-time inventory updates.

    Connect with: ws://host/ws/inventory?store_id=1
    Messages are JSON with 'type' field indicating the update kind.
    """
    await hub.connect(websocket, store_id)
    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "store_id": store_id,
            "message": "Connected to inventory updates",
        })

        # Keep connection alive — listen for client messages (heartbeats, etc.)
        while True:
            data = await websocket.receive_text()
            # Echo back pings for keep-alive
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        hub.disconnect(websocket, store_id)
    except Exception:
        hub.disconnect(websocket, store_id)
