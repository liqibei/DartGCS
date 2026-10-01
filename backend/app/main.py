"""GCS 后端入口。

    Ubuntu:  cd backend && uvicorn app.main:app --port 8787
    Windows: cd backend && python -m app.main
             （必须走本入口：事件循环创建前设置 Selector 策略，
               ProactorEventLoop 不支持串口吞吐所需的部分异步设施）
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .api.routes import router
from .api.ws import WsHub
from .config import Settings
from .devices.manager import DeviceManager, FrameRing
from .links import LinkDriver, MockLink, SerialLink
from .services.archive import SessionArchive
from .services.hotspot import HotspotService
from .services.logs import LogService
from .services.monitor import MonitorService
from .services.params import ParamService
from .services.telemetry import TelemetryHub

if sys.platform == "win32":
    # Windows 默认 ProactorEventLoop 与 pyserial 线程读配合不佳，切回 Selector
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    settings.data_root.mkdir(parents=True, exist_ok=True)

    hub = TelemetryHub()
    ring = FrameRing()
    archive = SessionArchive(settings.data_root / "sessions")
    manager = DeviceManager(hub, ring)
    ws_hub = WsHub()
    params = ParamService(manager)
    monitor = MonitorService(manager, hub)
    logs = LogService(manager)
    hotspot = HotspotService(exposed=settings.host == "0.0.0.0", port=settings.api_port)

    links: list[LinkDriver] = []
    if settings.serial_port:
        links.append(SerialLink("serial", settings.serial_port, settings.baud))
    if settings.enable_mock or not links:
        links.append(MockLink("mock"))

    for link in links:
        link.on_frame = manager.handle_frame
        try:
            await link.start()
        except Exception:
            logger.exception("链路 %s 启动失败，跳过", link.name)
    manager.links = {link.name: link for link in links}

    bg = [
        asyncio.create_task(coro)
        for coro in (
            manager.lease_loop(),
            ws_hub.devices_loop(manager),
            ws_hub.telemetry_loop(hub),
        )
    ]
    app.state.settings = settings
    app.state.manager = manager
    app.state.hub = hub
    app.state.ring = ring
    app.state.archive = archive
    app.state.ws_hub = ws_hub
    app.state.params = params
    app.state.monitor = monitor
    app.state.logs = logs
    app.state.hotspot = hotspot
    app.state.links = links
    app.state.started_at = time.time()
    app.state.last_session_by_dart = {}
    logger.info(
        "GCS 后端就绪：serial=%s mock=%s data=%s",
        settings.serial_port, settings.enable_mock, settings.data_root,
    )
    try:
        yield
    finally:
        for task in bg:
            task.cancel()
        for link in reversed(links):
            try:
                await link.stop()
            except Exception:
                logger.exception("链路 %s 停止异常", link.name)


app = FastAPI(title="Dart GCS", version="0.2.0", lifespan=lifespan)
app.include_router(router)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    ws_hub: WsHub = ws.app.state.ws_hub
    manager = ws.app.state.manager
    await ws_hub.attach(ws)
    try:
        await ws.send_json({"type": "hello", "data": manager.snapshot()})
        while True:
            await ws.receive_text()  # 客户端消息仅作保活
    except WebSocketDisconnect:
        pass
    finally:
        ws_hub.detach(ws)


# 前端构建产物存在时由后端直接托管（单进程部署：一条命令即整站）
# 前端构建产物存在时由后端直接托管（单进程部署：一条命令即整站）。
# SPA 路由（/base 等）没有真实文件，回退到 index.html 由前端路由接管。
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith(("api/", "ws")):
            raise HTTPException(404)
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(app, host=settings.host, port=settings.api_port)
