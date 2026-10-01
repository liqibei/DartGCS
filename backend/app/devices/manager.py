"""设备管理器：单一 RX Owner + 待应答队列 + 帧环形缓冲。

所有链路的帧统一进 handle_frame（同步，保证帧序）。需要异步应答的动作
（参数/文件/发射等服务调用）通过 request() 走待应答队列：

- 匹配键 = (源设备ID, 应答CMD)，并校验应答 SEQ == 请求 SEQ（迟到旧应答直接丢弃）
- 每设备同时只有一个未完成请求（设备锁串行化），超时后以**新 SEQ** 重发
- 数据面帧（心跳/采样/状态）不应答，SEQ 用于丢帧率统计与重启检测
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from collections import deque
from typing import TYPE_CHECKING

from ..protocol import (
    BASE_STATE,
    LAUNCHER_STATE,
    SYS_HEARTBEAT,
    SYS_HOST_STATS,
    BlockCmds,
    Frame,
    build_frame,
)
from ..protocol.cmd import DATA_PLANE_CMDS, RESPONSE_OF, response_of
from .device import Device, kind_of

if TYPE_CHECKING:
    from ..links.base import LinkDriver
    from ..services.telemetry import TelemetryHub

logger = logging.getLogger(__name__)


class DeviceTimeout(Exception):
    pass


class FrameRing:
    """最近帧环形缓冲：协议诊断页的数据源。"""

    def __init__(self, maxlen: int = 2000) -> None:
        self._dq: deque[dict] = deque(maxlen=maxlen)

    def push(self, direction: str, link_name: str, frame: Frame) -> None:
        self._dq.append(
            {
                "ts": time.time(),
                "dir": direction,
                "link": link_name,
                "src": f"0x{frame.id:02X}",
                "type": f"0x{frame.cmd:04X}",
                "len": len(frame.payload),
                "hex": frame.payload[:48].hex(),
            }
        )

    def recent(self, limit: int = 200) -> list[dict]:
        return list(self._dq)[-limit:]


class Pending:
    __slots__ = ("rsp_cmd", "sent_seq", "attempts", "event", "response")

    def __init__(self, rsp_cmd: int, sent_seq: int, attempts: int) -> None:
        self.rsp_cmd = rsp_cmd
        self.sent_seq = sent_seq
        self.attempts = attempts
        self.event = asyncio.Event()
        self.response: Frame | None = None


class DeviceManager:
    HEARTBEAT_TIMEOUT = 3.0

    def __init__(self, hub: "TelemetryHub", ring: FrameRing) -> None:
        self.devices: dict[int, Device] = {}
        self.hub = hub
        self.ring = ring
        self.links: dict[str, "LinkDriver"] = {}  # main 启动后注入
        self.pending: dict[tuple[int, int], Pending] = {}
        self._dev_locks: dict[int, asyncio.Lock] = {}
        self._tx_seq = 0
        # 变量采样帧监听（monitor 服务注入）
        self.sample_listener: Callable[[int, bytes], None] | None = None

    # -- 入向（唯一帧入口）-------------------------------------------------
    def handle_frame(self, frame: Frame, link: "LinkDriver") -> None:
        now = time.time()
        dev = self.devices.get(frame.id)
        if dev is None:
            dev = Device(id=frame.id, first_seen=now, last_seen=now, link_name=link.name)
            self.devices[frame.id] = dev
            logger.info("发现设备 %s (0x%02X) @%s", dev.name, dev.id, link.name)
        dev.last_seen = now
        dev.online = True
        dev.link_name = link.name
        self.ring.push("in", link.name, frame)

        if frame.cmd in DATA_PLANE_CMDS:
            dev.on_data_frame(frame.seq)

        # 控制面应答：按 (源ID, 应答CMD) 匹配，SEQ 校验防迟到错配
        key = (frame.id, frame.cmd)
        p = self.pending.get(key)
        if p is not None:
            if p.sent_seq == frame.seq:
                self.pending.pop(key, None)
                p.response = frame
                p.event.set()
            return  # 应答帧不再进入业务解析

        if frame.cmd == SYS_HEARTBEAT and len(frame.payload) >= 3:
            dev.battery_mv, dev.flags = struct.unpack("<HB", frame.payload[:3])
        elif self._is_samples_cmd(frame.cmd) and self.sample_listener:
            self.sample_listener(frame.id, frame.payload)
        elif frame.cmd == LAUNCHER_STATE and len(frame.payload) >= 12:
            state, in_place, trig = struct.unpack_from("<BBH", frame.payload, 0)
            pitch, yaw = struct.unpack_from("<ff", frame.payload, 4)
            now_ns = now
            self.hub.update(frame.id, 0x71, state, now_ns, name="state")
            self.hub.update(frame.id, 0x72, in_place, now_ns, name="darts_in_place")
            self.hub.update(frame.id, 0x73, trig, now_ns, name="trigger_mv")
            self.hub.update(frame.id, 0x74, pitch, now_ns, name="pitch_deg")
            self.hub.update(frame.id, 0x75, yaw, now_ns, name="yaw_deg")
        elif frame.cmd == BASE_STATE and len(frame.payload) >= 9:
            cur, tgt = struct.unpack_from("<ff", frame.payload, 0)
            running = frame.payload[8]
            self.hub.update(frame.id, 0x71, cur, now, name="cur_pos_mm")
            self.hub.update(frame.id, 0x72, tgt, now, name="tgt_pos_mm")
            self.hub.update(frame.id, 0x73, running, now, name="running")
            if len(frame.payload) >= 10:  # v0.2.1：BSTATE 追加灯位
                self.hub.update(frame.id, 0x74, frame.payload[9], now, name="light")
            if len(frame.payload) >= 11:  # v0.2.1：BSTATE 追加舱门位
                self.hub.update(frame.id, 0x75, frame.payload[10], now, name="door")
            if len(frame.payload) >= 12:  # v0.2.1：BSTATE 追加开启状态位
                self.hub.update(frame.id, 0x76, frame.payload[11], now, name="started")
        # 其余帧已入环形缓冲，由服务层按需处理

    @staticmethod
    def _is_samples_cmd(cmd: int) -> bool:
        return any(cmd == blk.base + 0x110 for blk in (BlockCmds(0x1000), BlockCmds(0x2000), BlockCmds(0x3000)))

    # -- 出向 ---------------------------------------------------------------
    def _next_seq(self) -> int:
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return self._tx_seq

    def link_for_device(self, dev_id: int) -> "LinkDriver | None":
        dev = self.devices.get(dev_id)
        return self.links.get(dev.link_name) if dev else None

    async def send(self, dev_id: int, cmd: int, data: bytes = b"", *, seq: int | None = None) -> None:
        link = self.link_for_device(dev_id)
        if link is None:
            raise DeviceTimeout(f"设备 0x{dev_id:02X} 无链路")
        if seq is None:
            seq = self._next_seq()
        frame = Frame(id=dev_id, cmd=cmd, seq=seq, payload=data)
        self.ring.push("out", link.name, frame)
        await link.send_frame(frame, dst=dev_id)

    async def request(
        self,
        dev_id: int,
        cmd: int,
        data: bytes = b"",
        *,
        timeout: float = 0.2,
        retries: int = 2,
    ) -> Frame:
        """控制面请求-应答：超时以新 SEQ 重发；每设备串行化。"""
        rsp_cmd = response_of(cmd)
        if rsp_cmd is None:
            raise ValueError(f"CMD 0x{cmd:04X} 未定义应答")
        lock = self._dev_locks.setdefault(dev_id, asyncio.Lock())
        async with lock:
            last: Exception | None = None
            for attempt in range(retries + 1):
                seq = self._next_seq()
                p = Pending(rsp_cmd=rsp_cmd, sent_seq=seq, attempts=attempt + 1)
                key = (dev_id, rsp_cmd)
                self.pending[key] = p
                try:
                    await self.send(dev_id, cmd, data, seq=seq)
                    await asyncio.wait_for(p.event.wait(), timeout)
                    return p.response  # type: ignore[return-value]
                except asyncio.TimeoutError:
                    self.pending.pop(key, None)
                    last = DeviceTimeout(
                        f"0x{dev_id:02X} CMD 0x{cmd:04X} 第 {attempt + 1} 次尝试无应答"
                    )
                    logger.warning(str(last))
            raise last  # type: ignore[misc]

    # -- 维护 ----------------------------------------------------------------
    async def lease_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            now = time.time()
            for dev in self.devices.values():
                dev.online = (now - dev.last_seen) < self.HEARTBEAT_TIMEOUT

    def snapshot(self) -> list[dict]:
        return [dev.to_dict(self.hub) for dev in sorted(self.devices.values(), key=lambda d: d.id)]
