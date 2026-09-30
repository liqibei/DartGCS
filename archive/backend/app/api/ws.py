"""WebSocket 推送：设备快照（1s）+ 遥测批次（100ms）。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WsHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def attach(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def detach(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def devices_loop(self, manager, interval: float = 1.0) -> None:
        while True:
            await asyncio.sleep(interval)
            await self.broadcast({"type": "devices", "data": manager.snapshot()})

    async def telemetry_loop(self, hub, interval: float = 0.1) -> None:
        while True:
            await asyncio.sleep(interval)
            pending = hub.take_pending()
            if pending:
                await self.broadcast({"type": "telemetry", "data": pending})
