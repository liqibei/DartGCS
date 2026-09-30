"""Mock 链路：进程内仿真 C3 主机 + 全部从机，走真实协议栈。

覆盖协议草案 v0.2 的全部 CMD 块：
- 系统管理：心跳 2Hz / PROBE 回显 / FW_VERSION / REBOOT / TIME_SYNC(忽略)
- 参数服务：目录分页 / 双值读写 / SAVE / 恢复出厂（三设备各自目录）
- 变量监视：目录 / 订阅制采样（只发被订阅变量，50ms 攒批）
- 飞行日志：飞镖 16KB 假 CSV，分块拉取
- 镖架：LSTATE 5Hz（状态机+在位+触发装置电压）/ 单发 / 四发 / 急停 / 模式
- 基地：BSTATE 运动学（位置向目标爬升）/ 四档模式 / 目标位置 / 启停
- 主机：HOST_STATS 1Hz

仿真帧全部经 build_frame/FrameParser，即 Mock 验证的正是协议栈本身。
"""
from __future__ import annotations

import asyncio
import logging
import math
import struct
import time

from ..protocol import (
    BASE_MODE,
    BASE_RUN,
    BASE_STATE,
    BASE_TARGET,
    BlockCmds,
    DBG_ECHO,
    LAUNCHER_MODE,
    LAUNCHER_STATE,
    LAUNCH_ABORT,
    LAUNCH_FOUR,
    LAUNCH_RESULT,
    LAUNCH_SINGLE,
    LOG_CHUNK,
    LOG_CHUNK_REQ,
    LOG_ERASE,
    LOG_INFO_GET,
    SYS_FW_VERSION,
    SYS_HEARTBEAT,
    SYS_HOST_STATS,
    SYS_PROBE,
    SYS_REBOOT,
    SYS_TIME_SYNC,
    Frame,
    FrameParser,
    build_frame,
    dart_id,
)
from ..protocol.value import (
    BOOL,
    F32,
    U8,
    U16,
    ParamEntry,
    VarEntry,
    pack_value,
    unpack_value,
)
from .base import LinkDriver

logger = logging.getLogger(__name__)

CHUNK = 232  # 日志分块数据上限（DATA 240 - 头 8B）

PROTO_VER = 2
FW_VER = b"mock-fw 0.1.0"

RESULT_OK = 0
RESULT_STATE_DENIED = 2


def _up(link: LinkDriver, dev_id: int, cmd: int, payload: bytes, seq: int) -> None:
    link.feed_bytes(build_frame(cmd, payload, dev_id, seq))


class _SimDevice:
    """仿真从机基类：参数目录 + 变量目录 + 心跳。"""

    heartbeat_period = 0.5
    battery0 = 7600
    drain_mv_s = 8.0

    def __init__(self, link: "MockLink", dev_id: int) -> None:
        self.link = link
        self.id = dev_id
        self.cmds: BlockCmds | None = None  # 子类构造时覆盖
        self.params: list[ParamEntry] = []
        self.saved: dict[int, float] = {}
        self.current: dict[int, float] = {}
        self.vars: dict[int, VarEntry] = {}
        self.var_fn: dict[int, object] = {}
        self.subs: dict[int, int] = {}
        self.data_seq = 0
        self.t0 = time.monotonic()

    # ---- 组帧 ----
    def _dseq(self) -> int:
        self.data_seq = (self.data_seq + 1) & 0xFF
        return self.data_seq

    def up(self, cmd: int, payload: bytes, seq: int) -> None:
        _up(self.link, self.id, cmd, payload, seq)

    def up_data(self, cmd: int, payload: bytes) -> None:
        _up(self.link, self.id, cmd, payload, self._dseq())

    # ---- 参数/变量目录（通用）----
    def _paged(self, page: int, entries: list[bytes], per: int) -> bytes:
        return struct.pack("<HH", page, len(entries)) + b"".join(
            entries[page * per : (page + 1) * per]
        )

    def _param_entries(self) -> list[bytes]:
        return [p.encode() for p in self.params]

    def _var_entries(self) -> list[bytes]:
        return [v.encode() for v in self.vars.values()]

    # ---- 下行分发 ----
    def handle(self, cmd: int, data: bytes, seq: int) -> None:
        c = self.cmds
        if cmd == c.catalog_get:
            (page,) = struct.unpack_from("<H", data, 0)
            self.up(c.catalog_rsp, self._paged(page, self._param_entries(), 5), seq)
        elif cmd == c.read:
            (pid,) = struct.unpack_from("<H", data, 0)
            self.up(c.read_rsp, struct.pack("<H", pid)
                    + pack_value(self._type(pid), self.saved[pid])
                    + pack_value(self._type(pid), self.current[pid]), seq)
        elif cmd == c.write:
            (pid,) = struct.unpack_from("<H", data, 0)
            p = self._param(pid)
            self.current[pid] = unpack_value(p.type, data[2:10])
            self.up(c.write_rsp, struct.pack("<HB", pid, RESULT_OK), seq)
        elif cmd == c.save:
            for p in self.params:
                self.saved[p.pid] = self.current[p.pid]
            self.up(c.write_rsp, struct.pack("<H", 0xFFFF) + bytes([RESULT_OK]), seq)
        elif cmd == c.reset:
            for p in self.params:
                self.saved[p.pid] = p.default
                self.current[p.pid] = p.default
            self.up(c.write_rsp, struct.pack("<H", 0xFFFF) + bytes([RESULT_OK]), seq)
        elif cmd == c.var_catalog_get:
            (page,) = struct.unpack_from("<H", data, 0)
            self.up(c.var_catalog_rsp, self._paged(page, self._var_entries(), 15), seq)
        elif cmd == c.var_subscribe:
            (count,) = struct.unpack_from("<B", data, 0)
            for i in range(count):
                vid, rate = struct.unpack_from("<BB", data, 1 + i * 2)
                self.subs[vid] = min(rate, 100)
            self.up(c.var_subscribe, bytes([count]), seq)
        elif cmd == c.var_unsubscribe:
            (count,) = struct.unpack_from("<B", data, 0)
            for i in range(count):
                self.subs.pop(data[1 + i], None)
            self.up(c.var_unsubscribe, bytes([count]), seq)
        elif cmd == SYS_PROBE or cmd == DBG_ECHO:
            if not data.startswith(b"ack:"):
                self.up(cmd, b"ack:" + data[:64], seq)
        elif cmd == SYS_FW_VERSION:
            self.up(SYS_FW_VERSION, struct.pack("<B", PROTO_VER) + FW_VER.ljust(16), seq)
        elif cmd == SYS_REBOOT:
            self.up(SYS_REBOOT, b"", seq)
        elif cmd == SYS_TIME_SYNC:
            pass  # 无应答
        else:
            self.on_cmd(cmd, data, seq)

    # ---- 子类钩子 ----
    def on_cmd(self, cmd: int, data: bytes, seq: int) -> None:
        pass

    # ---- 周期任务 ----
    async def run(self) -> None:
        hb_next = 0.0
        while True:
            now = time.monotonic()
            if now >= hb_next:
                hb_next = now + self.heartbeat_period
                battery = max(6000, int(self.battery0 - (now - self.t0) * self.drain_mv_s))
                self.up_data(SYS_HEARTBEAT, struct.pack("<HB", battery, 0))
            self.periodic(now - self.t0)
            self._emit_samples()
            await asyncio.sleep(0.05)

    def periodic(self, t: float) -> None:
        pass

    def _emit_samples(self) -> None:
        if not self.subs:
            return
        entries = b"".join(
            struct.pack("<Bf", vid, float(self.var_fn[vid](time.monotonic() - self.t0)))
            for vid in self.subs
            if vid in self.var_fn
        )
        if entries:
            self.up_data(self.cmds.var_samples, entries)

    # ---- 参数辅助 ----
    def _param(self, pid: int) -> ParamEntry:
        return next(p for p in self.params if p.pid == pid)

    def _type(self, pid: int) -> int:
        return self._param(pid).type

    def add_param(self, pid: int, name: str, type_: int, unit: str,
                  mn: float, mx: float, default: float) -> None:
        self.params.append(ParamEntry(pid, name, type_, unit, mn, mx, default))
        self.saved[pid] = default
        self.current[pid] = default

    def add_var(self, vid: int, name: str, unit: str, rate: int, fn) -> None:
        self.vars[vid] = VarEntry(vid, name, unit, rate)
        self.var_fn[vid] = fn


class _DartSim(_SimDevice):
    heartbeat_period = 0.5
    battery0 = 8100
    drain_mv_s = 2.0

    def __init__(self, link: "MockLink", n: int) -> None:
        super().__init__(link, dart_id(n))
        self.cmds = BlockCmds(0x1000)
        for i, (name, unit) in enumerate(
            [("pitch_kp", ""), ("pitch_ki", ""), ("yaw_kp", ""), ("yaw_ki", ""),
             ("servo_min", "us"), ("servo_max", "us"), ("log_rate", "Hz"),
             ("lead_angle", "deg"), ("trig_min_mv", "mV"), ("calib", "")], start=1):
            spec = {1: (F32, 0, 50, 2.0), 2: (F32, 0, 5, 0.2), 3: (F32, 0, 50, 2.0),
                    4: (F32, 0, 5, 0.2), 5: (U16, 500, 2500, 1000), 6: (U16, 500, 2500, 2000),
                    7: (U8, 1, 50, 10), 8: (F32, -30, 30, 0.0),
                    9: (U16, 3600, 4200, 4000), 10: (F32, -1, 1, 0.0)}[i]
            self.add_param(i, name, spec[0], unit, spec[1], spec[2], spec[3])
        for i, (name, unit) in enumerate(
            [("height_m", "m"), ("speed_ms", "m/s"), ("pitch_deg", "deg"),
             ("roll_deg", "deg"), ("yaw_deg", "deg"), ("servo_l", "deg"),
             ("servo_r", "deg")], start=1):
            self.add_var(i, name, unit, 50,
                         lambda t, i=i: [20 + 15 * math.sin(0.7 * t), 18 + 4 * math.sin(0.5 * t),
                                         35 + 5 * math.sin(0.9 * t), 8 * math.sin(1.3 * t),
                                         90 + 20 * math.sin(0.3 * t), 3 * math.sin(2.1 * t),
                                         -3 * math.sin(2.1 * t)][i - 1])
        rows = ["t,height,speed,pitch,roll,yaw"]
        k = 0
        while len("\n".join(rows).encode()) < 16 * 1024 - 8:
            t = k / 400
            rows.append(f"{t:.3f},{20 + 15 * math.sin(0.7 * t):.2f},{18:.2f},"
                        f"{35:.2f},{0:.2f},{90:.2f}")
            k += 1
        self.log = ("\n".join(rows) + "\n").encode().ljust(16 * 1024, b"\n")[: 16 * 1024]
        self.log_ts = int(time.time())

    def on_cmd(self, cmd: int, data: bytes, seq: int) -> None:
        if cmd == LOG_INFO_GET:
            payload = struct.pack("<B", 1) + struct.pack("<BII", 1, len(self.log), self.log_ts)
            self.up(0x1201, payload, seq)
        elif cmd == LOG_CHUNK_REQ:
            log_id, chunk = struct.unpack_from("<BH", data, 0)
            total = (len(self.log) + CHUNK - 1) // CHUNK
            off = chunk * CHUNK
            piece = self.log[off : off + CHUNK]
            self.up(LOG_CHUNK, struct.pack("<BHH", log_id, chunk, total) + piece, seq)
        elif cmd == LOG_ERASE:
            self.up(LOG_CHUNK, struct.pack("<BHH", data[0] if data else 1, 0xFFFF, 0), seq)


class _LauncherSim(_SimDevice):
    heartbeat_period = 0.5
    battery0 = 25000
    drain_mv_s = 1.0

    def __init__(self, link: "MockLink") -> None:
        super().__init__(link, 0x10)
        self.cmds = BlockCmds(0x2000)
        for i in range(4):
            self.add_param(1 + i, f"slot{i + 1}_yaw", F32, "deg", -5, 5, 0.0)
            self.add_param(5 + i, f"slot{i + 1}_force", F32, "N", 0, 120, 60.0)
        self.add_var(1, "pitch_deg", "deg", 5, lambda t: 35 + 2 * math.sin(0.4 * t))
        self.add_var(2, "yaw_deg", "deg", 5, lambda t: 3 * math.sin(0.2 * t))
        self.mode = 1  # 0=安全 1=待命
        self.last_launch: tuple[int, float, float, float] | None = None

    def periodic(self, t: float) -> None:
        pitch, yaw = 35 + 2 * math.sin(0.4 * t), 3 * math.sin(0.2 * t)
        trig = max(4000, int(4200 - t * 0.5))
        self.up_data(LAUNCHER_STATE,
                     struct.pack("<BBHff", self.mode + 1, 0b1111, trig, pitch, yaw))

    def on_cmd(self, cmd: int, data: bytes, seq: int) -> None:
        if cmd == LAUNCH_SINGLE:
            slot = data[0]
            if self.mode == 0:
                self._result(seq, RESULT_STATE_DENIED, slot)
                return
            self.last_launch = (slot, *struct.unpack_from("<fff", data, 1))
            self.link._spawn(self._delayed_result(seq, RESULT_OK, slot, 0.03))
        elif cmd == LAUNCH_FOUR:
            if self.mode == 0:
                self._result(seq, RESULT_STATE_DENIED, 0xFF)
                return
            self.link._spawn(self._delayed_result(seq, RESULT_OK, 0xFF, 0.08))
        elif cmd == LAUNCH_ABORT:
            self._result(seq, RESULT_OK, 0xFE)
        elif cmd == LAUNCHER_MODE:
            if data:
                self.mode = data[0]
            self.up(LAUNCHER_MODE, bytes([self.mode]), seq)

    def _result(self, seq: int, code: int, slot: int) -> None:
        self.up(LAUNCH_RESULT, struct.pack("<BB", code, slot), seq)

    async def _delayed_result(self, seq: int, code: int, slot: int, delay: float) -> None:
        await asyncio.sleep(delay)
        self._result(seq, code, slot)


class _BaseSim(_SimDevice):
    heartbeat_period = 0.5
    battery0 = 11900
    drain_mv_s = 0.5

    def __init__(self, link: "MockLink") -> None:
        super().__init__(link, 0x20)
        self.cmds = BlockCmds(0x3000)
        self.add_param(1, "speed", F32, "mm/s", 100, 2000, 500.0)
        self.add_param(2, "accel", F32, "mm/s2", 100, 5000, 1000.0)
        self.add_param(3, "range", F32, "mm", 100, 280, 280.0)
        self.add_param(4, "home", F32, "mm", -280, 280, 0.0)
        self.mode = 0
        self.cur = 0.0
        self.target = 0.0
        self.running = 0

    def periodic(self, t: float) -> None:
        if self.running:
            step = float(self.current[1]) * 0.05
            if abs(self.target - self.cur) <= step:
                self.cur = self.target
            else:
                self.cur += step if self.target > self.cur else -step
        self.up_data(BASE_STATE, struct.pack("<ffB", self.cur, self.target, self.running))

    def on_cmd(self, cmd: int, data: bytes, seq: int) -> None:
        if cmd == BASE_MODE:
            if data:
                self.mode = data[0]
            self.up(BASE_MODE, bytes([self.mode]), seq)
        elif cmd == BASE_TARGET:
            (self.target,) = struct.unpack_from("<f", data, 0)
            self.up(BASE_TARGET, struct.pack("<f", self.target), seq)
        elif cmd == BASE_RUN:
            self.running = data[0] if data else 0
            self.up(BASE_RUN, bytes([self.running]), seq)


class _HostSim:
    """C3 主机仿真：固件版本 + 链路统计（透传语义由 Mock 分发天然满足）。"""

    id = 0xFE

    def __init__(self, link: "MockLink", devices: list[_SimDevice]) -> None:
        self.link = link
        self.devices = devices
        self.data_seq = 0

    def handle(self, cmd: int, data: bytes, seq: int) -> None:
        if cmd == SYS_FW_VERSION:
            self.link.feed_bytes(
                build_frame(SYS_FW_VERSION, struct.pack("<B", PROTO_VER) + FW_VER.ljust(16),
                            self.id, seq))
        elif cmd == SYS_PROBE and not data.startswith(b"ack:"):
            self.link.feed_bytes(
                build_frame(SYS_PROBE, b"ack:" + data[:64], self.id, seq))

    async def run(self) -> None:
        while True:
            self.data_seq = (self.data_seq + 1) & 0xFF
            rows = b"".join(
                struct.pack("<BbB", d.id, -50 - 3 * (d.id % 7), 0) for d in self.devices
            )
            self.link.feed_bytes(
                build_frame(SYS_HOST_STATS, struct.pack("<B", len(self.devices)) + rows,
                            self.id, self.data_seq))
            await asyncio.sleep(1.0)


class MockLink(LinkDriver):
    """仿真链路：PC 视角即 C3 主机 + 全部从机。"""

    def __init__(self, name: str = "mock") -> None:
        super().__init__(name)
        self._downlink = FrameParser()
        self.launcher = _LauncherSim(self)
        self.base = _BaseSim(self)
        self.darts = [_DartSim(self, 1), _DartSim(self, 2)]
        self.host = _HostSim(self, [self.launcher, self.base, *self.darts])
        self._by_id = {d.id: d for d in (self.launcher, self.base, *self.darts)}
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        for sim in (self.launcher, self.base, *self.darts):
            self._spawn(sim.run())
        self._spawn(self.host.run())
        logger.info("Mock 链路启动：LAUNCHER / BASE / DART-01 / DART-02 / C3-HOST")

    async def send_raw(self, data: bytes, dst: int | None = None) -> None:
        for frame in self._downlink.feed(data):
            if frame.id == 0xFF:
                for sim in self._by_id.values():
                    sim.handle(frame.cmd, frame.payload, frame.seq)
                self.host.handle(frame.cmd, frame.payload, frame.seq)
                continue
            sim = self._by_id.get(frame.id)
            if sim is not None:
                sim.handle(frame.cmd, frame.payload, frame.seq)
            elif frame.id == self.host.id:
                self.host.handle(frame.cmd, frame.payload, frame.seq)
            # 未知 ID：主机语义应为丢弃并计数，这里静默
