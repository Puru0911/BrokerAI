from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class RealtimeHub:
    """In-process WebSocket fan-out. One uvicorn worker is enough for the MVP."""

    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = {}

    def register(self, user_id: str, websocket: WebSocket) -> None:
        self._sockets.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        sockets = self._sockets.get(user_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._sockets.pop(user_id, None)

    def is_online(self, user_id: str) -> bool:
        return bool(self._sockets.get(user_id))

    async def send_to_user(self, user_id: str, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for websocket in list(self._sockets.get(user_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:
                logger.debug("websocket send failed user=%s", user_id, exc_info=True)
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(user_id, websocket)


hub = RealtimeHub()
