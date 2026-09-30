"""GCS 后端入口。

    Ubuntu:  cd backend && uvicorn app.main:app --port 8787
    Windows: cd backend && python -m app.main
             （必须走本入口：需在事件循环创建前设置 Selector 策略，
               ProactorEventLoop 不支持 UDP datagram endpoint）
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .api.ws import WsHub
from .config import Settings
from .devices.manager import DeviceManager, FrameRing
from .links import LinkDriver, MockLink, SerialLink, TcpLink, UdpLink
from .services.archive import SessionArchive
from .services.telemetry import TelemetryHub

if sys.platform == "win32":
    # Windows 默认 ProactorEventLoop 不支持 create_datagram_endpoint（UdpLink 依赖），
    # 切回 Selector 循环；本模块被 import 时设置即可覆盖 python -m app.main 的启动路径。
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

    links: list[LinkDriver] = [UdpLink("udp", settings.udp_port), TcpLink("tcp", settings.tcp_port)]
    for i, port in enumerate(settings.serial_ports):
        links.append(SerialLink(f"serial{i}", port))
    if settings.enable_mock:
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
        for coro in (manager.lease_loop(), ws_hub.devices_loop(manager), ws_hub.telemetry_loop(hub))
    ]
    app.state.settings = settings
    app.state.manager = manager
    app.state.hub = hub
    app.state.ring = ring
    app.state.archive = archive
    app.state.ws_hub = ws_hub
    app.state.links = links
    app.state.started_at = time.time()
    logger.info(
        "GCS 后端就绪：mock=%s serial=%s data=%s", settings.enable_mock, settings.serial_ports, settings.data_root
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


app = FastAPI(title="Dart GCS", version="0.1.0", lifespan=lifespan)
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


# 前端构建产物存在时由后端直接托管（单进程部署：python -m app.main 即整站）
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(app, host=settings.host, port=settings.api_port)
