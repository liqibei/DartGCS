"""端到端集成测试：GCS 协议栈 + Mock 设备全流程。

验证协议草案 v0.2 的每个 CMD 块：发现/探针、参数目录与双值读写、
订阅制变量监视、飞行日志分块拉取、发射联锁、基地运动。
"""
import asyncio
import struct

import pytest

from app.devices.manager import DeviceManager, FrameRing
from app.links.mock_link import MockLink
from app.protocol import dart_id
from app.protocol.cmd import LAUNCHER_MODE, LAUNCH_SINGLE, LAUNCH_RESULT
from app.services.logs import LogService
from app.services.monitor import MonitorService
from app.services.params import ParamService
from app.services.telemetry import TelemetryHub


def _make():
    hub = TelemetryHub()
    ring = FrameRing()
    manager = DeviceManager(hub, ring)
    link = MockLink("mock")
    link.on_frame = manager.handle_frame
    manager.links = {"mock": link}
    return manager, link, hub


def _run(coro):
    return asyncio.run(coro)


async def _boot(manager, link, wait=0.9):
    await link.start()
    await asyncio.sleep(wait)  # 心跳到位、设备表建立


def test_probe_and_discovery():
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            assert 0x10 in manager.devices
            assert 0x20 in manager.devices
            assert dart_id(1) in manager.devices
            assert dart_id(2) in manager.devices
            assert 0xFE in manager.devices
            rsp = await manager.request(dart_id(1), 0x0E00, b"ping")
            assert rsp.payload.startswith(b"ack:ping")
        finally:
            await link.stop()

    _run(run())


def test_param_catalog_read_write_save():
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            params = ParamService(manager)
            catalog = await params.get_catalog(dart_id(1))
            assert len(catalog) == 10
            assert catalog[0].name == "pitch_kp"
            saved, current = await params.read(dart_id(1), 1)
            assert saved == pytest.approx(2.0) and current == pytest.approx(2.0)
            assert await params.write(dart_id(1), 1, 3.5) == 0
            saved, current = await params.read(dart_id(1), 1)
            assert saved == pytest.approx(2.0) and current == pytest.approx(3.5)
            assert await params.save(dart_id(1)) == 0
            saved, current = await params.read(dart_id(1), 1)
            assert saved == pytest.approx(3.5)
            assert await params.reset(dart_id(1)) == 0
            saved, _ = await params.read(dart_id(1), 1)
            assert saved == pytest.approx(2.0)
        finally:
            await link.stop()

    _run(run())


def test_variable_monitor_subscription():
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            monitor = MonitorService(manager, hub)
            catalog = await monitor.get_catalog(dart_id(1))
            assert len(catalog) == 7
            await monitor.subscribe(dart_id(1), [{"id": 1, "rate": 50}, {"id": 3, "rate": 50}])
            await asyncio.sleep(0.4)
            names = {s["name"] for s in hub.snapshot(dart_id(1))}
            assert "height_m" in names and "pitch_deg" in names
            # 未订阅的变量不应出现
            assert "yaw_deg" not in names
        finally:
            await link.stop()

    _run(run())


def test_log_pull_16k():
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            logs = LogService(manager)
            infos = await logs.list_logs(dart_id(1))
            assert infos and infos[0]["size"] >= 16 * 1024 - 1024
            data = await logs.pull(dart_id(1), 1)
            assert len(data) == 16 * 1024
            assert data.startswith(b"t,height,speed")
        finally:
            await link.stop()

    _run(run())


def test_launcher_interlock_and_fire():
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            payload = struct.pack("<Bfff", 1, 60.0, 35.0, 0.0)
            rsp = await manager.request(0x10, LAUNCH_SINGLE, payload, timeout=0.5)
            assert rsp.cmd == LAUNCH_RESULT and rsp.payload[0] == 0
            # 切安全模式 → 发射被联锁拒绝（STATE_DENIED=2，不是超时）
            await manager.request(0x10, LAUNCHER_MODE, b"\x00")
            rsp = await manager.request(0x10, LAUNCH_SINGLE, payload, timeout=0.5)
            assert rsp.payload[0] == 2
        finally:
            await link.stop()

    _run(run())


def test_base_motion():
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            await manager.request(0x20, 0x3201, b"\x02")           # 随机移动档
            await manager.request(0x20, 0x3202, struct.pack("<f", 200.0))
            await manager.request(0x20, 0x3203, b"\x01")           # 启动
            await asyncio.sleep(0.8)                                # 500mm/s 爬升
            snap = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert snap["cur_pos_mm"] == pytest.approx(200.0, abs=30)
            # 停止
            await manager.request(0x20, 0x3203, b"\x00")
        finally:
            await link.stop()

    _run(run())


def test_loss_stats_and_reboot_detection():
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link, wait=1.2)
        try:
            dev = manager.devices[dart_id(1)]
            assert dev.rx_count >= 2
            assert dev.loss_rate == 0.0  # Mock 不丢帧
        finally:
            await link.stop()

    _run(run())
