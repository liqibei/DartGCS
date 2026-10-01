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
from app.protocol.value import pack_value, U16


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
            await manager.request(0x20, 0x3203, b"\x01")           # 使能
            await manager.request(0x20, 0x3201, b"\x00")           # 固定档
            await manager.request(0x20, 0x3202, struct.pack("<fB", 200.0, 0))  # 切换目标 → 自动停止
            await asyncio.sleep(0.2)
            mid = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert mid["tgt_pos_mm"] == 200.0 and mid["cur_pos_mm"] < 100  # 停在原地未前往
            await manager.request(0x20, 0x3205, b"\x01")           # 开始指令 → 前往目标
            await asyncio.sleep(0.8)                                # 500mm/s 爬升
            snap = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert snap["cur_pos_mm"] == pytest.approx(200.0, abs=30)
            # 失能：运动程序清空
            await manager.request(0x20, 0x3203, b"\x00")
        finally:
            await link.stop()

    _run(run())


def test_base_light_and_state():
    """v0.2.1：灯开关 + BSTATE 灯位上报 + BMODE_GET 空载读模式。"""
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            await manager.request(0x20, 0x3204, b"\x01")            # 开灯
            await manager.request(0x20, 0x3201, b"\x01")            # 末端移动档
            rsp = await manager.request(0x20, 0x3201, b"")           # 空载=读回
            assert rsp.payload[0] == 1
            await asyncio.sleep(0.15)
            snap = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert snap["light"] == 1
        finally:
            await link.stop()

    _run(run())


def test_base_door_and_trigger():
    """v0.2.1：舱门开关 + 发射触发；失能下触发被拒绝（不隐式使能）。"""
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            await manager.request(0x20, 0x3205, b"\x01")            # 开舱门
            rsp = await manager.request(0x20, 0x3206, b"")           # 失能下触发
            assert rsp.payload[0] == 2                               # STATE_DENIED
            await manager.request(0x20, 0x3203, b"\x01")             # 使能
            rsp = await manager.request(0x20, 0x3206, b"")           # 使能后仍是停止状态：触发被拒
            assert rsp.payload[0] == 2
            await manager.request(0x20, 0x3205, b"\x01")            # 开始指令 → 开启状态
            rsp = await manager.request(0x20, 0x3206, b"")           # 再触发
            assert rsp.payload[0] == 1
            await asyncio.sleep(0.3)
            snap = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert snap["door"] == 1
            assert snap["running"] == 1
        finally:
            await link.stop()

    _run(run())


def test_base_speed_select_and_launch_delay():
    """v0.2.1：手动速度选择 + 随机移动的发射延迟时序（停住→停止速度冲刺→恢复巡航）。"""
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            # 随机固定档：使能不自动动；手动选停止速度（默认 1000mm/s），开始后 0.35s 走约 300mm
            await manager.request(0x20, 0x3201, b"\x01")
            await manager.request(0x20, 0x3203, b"\x01")
            await manager.request(0x20, 0x3202, struct.pack("<fB", -300.0, 1))
            await manager.request(0x20, 0x3205, b"\x01")   # 开始指令
            await asyncio.sleep(0.35)
            snap = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert snap["cur_pos_mm"] == pytest.approx(-300.0, abs=60)
            # 写发射延迟 200ms，切随机移动并使能（默认停止状态，触发被拒）
            await manager.request(0x20, 0x3004, struct.pack("<H", 4) + pack_value(U16, 200))
            await manager.request(0x20, 0x3203, b"\x00")
            await manager.request(0x20, 0x3201, b"\x02")
            await manager.request(0x20, 0x3203, b"\x01")
            await asyncio.sleep(0.15)
            p1 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}["cur_pos_mm"]
            await asyncio.sleep(0.2)
            p1b = {s["name"]: s["value"] for s in hub.snapshot(0x20)}["cur_pos_mm"]
            assert p1b == p1  # 使能完成默认停止
            rsp = await manager.request(0x20, 0x3206, b"")
            assert rsp.payload[0] == 2  # 停止状态：发射指令被拒绝
            # 开始指令 → 进入开启状态并巡航；发射指令有效（等待期巡航照常，延迟后冲刺）
            await manager.request(0x20, 0x3205, b"\x01")
            await asyncio.sleep(0.2)
            # 发射指令：延迟 200ms 后用停止速度冲刺
            await manager.request(0x20, 0x3206, b"")
            await asyncio.sleep(0.15)
            p2 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}["cur_pos_mm"]
            await asyncio.sleep(0.5)
            p3 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}["cur_pos_mm"]
            assert p3 != p2
        finally:
            await link.stop()

    _run(run())


def test_param_load_from_flash():
    """v0.2.1：PARAM_LOAD 把 flash 已存值恢复为当前值（放弃会话修改）。"""
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            svc = ParamService(manager)
            await svc.write(0x20, 1, 800.0)          # 会话修改平移速度
            await svc.save(0x20)                      # 存 flash
            await svc.write(0x20, 1, 300.0)           # 再改乱会话值
            assert (await svc.read(0x20, 1)) == (800.0, 300.0)
            assert await svc.load(0x20) == 0          # 从 flash 读取
            assert (await svc.read(0x20, 1)) == (800.0, 800.0)
        finally:
            await link.stop()

    _run(run())


def test_base_move_interval_dwell():
    """v0.2.1：随机移动到位后驻留「运动间隔」再换点，与行程长短无关。"""
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            await manager.request(0x20, 0x3004, struct.pack("<H", 3) + pack_value(U16, 300))
            await manager.request(0x20, 0x3201, b"\x02")   # 随机移动
            await manager.request(0x20, 0x3203, b"\x01")   # 使能（默认停止）
            await manager.request(0x20, 0x3205, b"\x01")   # 开始指令 → 巡航
            # 等第一次到位（位置 == 目标）
            snap = {}
            for _ in range(80):
                await asyncio.sleep(0.05)
                snap = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
                if snap["cur_pos_mm"] == snap["tgt_pos_mm"]:
                    break
            else:
                raise AssertionError("巡航未到位")
            # 驻留期内（<300ms）位置与目标都不变
            await asyncio.sleep(0.15)
            snap2 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert snap2["cur_pos_mm"] == snap["cur_pos_mm"]
            assert snap2["tgt_pos_mm"] == snap["tgt_pos_mm"]
            # 驻留期满换下一个随机点
            await asyncio.sleep(0.4)
            snap3 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert snap3["tgt_pos_mm"] != snap["tgt_pos_mm"] or snap3["cur_pos_mm"] != snap["cur_pos_mm"]
        finally:
            await link.stop()

    _run(run())


def test_base_stop_until_start():
    """v0.2.1：停止指令=原地停住；不发开始指令不再运动，开始指令后恢复。"""
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            await manager.request(0x20, 0x3201, b"\x02")   # 随机移动
            await manager.request(0x20, 0x3203, b"\x01")   # 使能 → 巡航
            await asyncio.sleep(0.3)
            await manager.request(0x20, 0x3205, b"\x00")   # 停止指令
            await asyncio.sleep(0.1)
            s1 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            await asyncio.sleep(1.0)
            s2 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert s1["running"] == 1                        # 保持使能
            assert s2["cur_pos_mm"] == s1["cur_pos_mm"]      # 停在原地
            # 停止状态下发射指令被拒绝
            rsp = await manager.request(0x20, 0x3206, b"")
            assert rsp.payload[0] == 2                       # STATE_DENIED
            await asyncio.sleep(3.0)
            s3 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert s3["cur_pos_mm"] == s1["cur_pos_mm"]      # 依旧停止（无自动恢复）
            # 开始指令 → 恢复开启状态并移动
            await manager.request(0x20, 0x3205, b"\x01")
            await asyncio.sleep(0.6)
            s4 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert s4["cur_pos_mm"] != s1["cur_pos_mm"] or s4["tgt_pos_mm"] != s1["tgt_pos_mm"]
        finally:
            await link.stop()

    _run(run())


def test_base_target_switch_stops():
    """v0.2.1：切换目标后自动停在原地；开始指令后前往新目标。"""
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            await manager.request(0x20, 0x3201, b"\x02")   # 随机移动
            await manager.request(0x20, 0x3203, b"\x01")   # 使能 → 巡航
            await asyncio.sleep(0.3)
            await manager.request(0x20, 0x3202, struct.pack("<fB", 200.0, 0))  # 切换目标
            await asyncio.sleep(0.2)
            s1 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert s1["tgt_pos_mm"] == 200.0
            assert s1["cur_pos_mm"] != 200.0                 # 自动停在原地，未前往
            await asyncio.sleep(0.5)
            s2 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert s2["cur_pos_mm"] == s1["cur_pos_mm"]      # 保持停止
            # 开始指令 → 前往 200 并驻留（运动间隔默认 0 → 到位后短暂驻留即巡航）
            await manager.request(0x20, 0x3205, b"\x01")
            hit = False
            for _ in range(50):
                await asyncio.sleep(0.05)
                s3 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
                if abs(s3["cur_pos_mm"] - 200.0) < 60:
                    hit = True
                    break
            assert hit, f"未前往目标 200：{s3}"
        finally:
            await link.stop()

    _run(run())


def test_base_manual_independent():
    """v0.2.1：手动目标为纯前往——到位即停，不带入自动巡航；自动程序需开始指令/发射指令启动。"""
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            # 自动模式随机移动巡航中，切手动下发目标：自动运动停止，前往目标后不再动
            await manager.request(0x20, 0x3201, b"\x02")
            await manager.request(0x20, 0x3203, b"\x01")
            await manager.request(0x20, 0x3205, b"\x01")   # 开始指令 → 巡航
            await asyncio.sleep(0.3)
            await manager.request(0x20, 0x3202, struct.pack("<fB", 200.0, 0))  # 手动目标 → 自动停
            await manager.request(0x20, 0x3205, b"\x01")   # 开始指令 → 纯前往 200
            hit = False
            for _ in range(50):
                await asyncio.sleep(0.05)
                s3 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
                if abs(s3["cur_pos_mm"] - 200.0) < 60:
                    hit = True
                    break
            assert hit, "未前往目标"
            # 到位后驻留观察 1.5s（运动间隔默认 0：若带入巡航会立刻换点运动）
            await asyncio.sleep(1.5)
            s4 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert s4["cur_pos_mm"] == 200.0 and s4["tgt_pos_mm"] == 200.0
        finally:
            await link.stop()

    _run(run())


def test_base_post_dash_freeze():
    """v0.2.1：发射指令冲刺到位后停到目标位置 10 秒（随机移动之后恢复巡航）。"""
    async def run():
        manager, link, hub = _make()
        await _boot(manager, link)
        try:
            await manager.request(0x20, 0x3201, b"\x02")   # 随机移动
            await manager.request(0x20, 0x3203, b"\x01")   # 使能（默认停止）
            await manager.request(0x20, 0x3205, b"\x01")   # 开始指令 → 巡航
            await asyncio.sleep(0.3)
            await manager.request(0x20, 0x3206, b"")       # 发射指令
            await asyncio.sleep(0.05)
            p0 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}["tgt_pos_mm"]
            # 等冲刺到位：位置==目标 且 目标已换成随机冲刺点（≠延迟停住时的目标）
            for _ in range(80):
                await asyncio.sleep(0.05)
                snap = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
                if snap["cur_pos_mm"] == snap["tgt_pos_mm"] and snap["tgt_pos_mm"] != p0:
                    break
            else:
                raise AssertionError("冲刺未到位")
            frozen = snap["cur_pos_mm"]
            # 到位后 10 秒内不再运动
            await asyncio.sleep(1.0)
            s2 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert s2["cur_pos_mm"] == frozen and s2["tgt_pos_mm"] == frozen
            await asyncio.sleep(2.0)
            s3 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert s3["cur_pos_mm"] == frozen and s3["tgt_pos_mm"] == frozen
            # 驻留期满恢复巡航
            await asyncio.sleep(8.0)
            s4 = {s["name"]: s["value"] for s in hub.snapshot(0x20)}
            assert s4["cur_pos_mm"] != frozen or s4["tgt_pos_mm"] != frozen
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
