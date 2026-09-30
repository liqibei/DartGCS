"""设备管理器：设备表 + 心跳租约 + 帧分发。

单一 RX Owner：所有链路的帧统一进 handle_frame（同步函数，保证帧序），
在此更新设备状态、分流遥测；需要异步的动作（Probe 应答）内部 create_task。
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from collections import deque
from typing import TYPE_CHECKING

from ..protocol.frame import ADDR_PC, Frame
from ..protocol.registry import (
    MSG_ID_DEBUG_ECHO,
    MSG_ID_HEARTBEAT,
    MSG_ID_TELEMETRY_SAMPLE,
    describe,
)
from .device import Device, device_name, kind_of_addr

if TYPE_CHECKING:
    from ..links.base import LinkDriver
    from ..services.telemetry import TelemetryHub

logger = logging.getLogger(__name__)


class FrameRing:
    """最近帧环形缓冲：协议诊断页的数据源。"""

    def __init__(self, maxlen: int = 2000) -> None:
        self._dq: deque[dict] = deque(maxlen=maxlen)

    def push(self, direction: str, link_name: str, frame: Frame) -> None:
        desc = describe(frame.type)
        self._dq.append(
            {
                "ts": time.time(),
                "dir": direction,
                "link": link_name,
                "src": f"0x{frame.src:02X}",
                "type": desc.name if desc else f"0x{frame.type:02X}",
                "plane": desc.plane if desc else "?",
                "len": len(frame.payload),
                "hex": frame.payload[:48].hex(),
            }
        )

    def recent(self, limit: int = 200) -> list[dict]:
        return list(self._dq)[-limit:]


class DeviceManager:
    HEARTBEAT_TIMEOUT = 3.0

    def __init__(self, hub: "TelemetryHub", ring: FrameRing) -> None:
        self.devices: dict[int, Device] = {}
        self.hub = hub
        self.ring = ring
        self.links: dict[str, "LinkDriver"] = {}  # main 启动后注入
        self._tx_seq = 0

    # -- 入向（唯一帧入口）-------------------------------------------------
    def handle_frame(self, frame: Frame, link: "LinkDriver") -> None:
        now = time.time()
        dev = self.devices.get(frame.src)
        if dev is None:
            dev = Device(
                addr=frame.src,
                kind=kind_of_addr(frame.src),
                name=device_name(frame.src),
                first_seen=now,
                last_seen=now,
            )
            self.devices[frame.src] = dev
            logger.info("发现设备 %s (0x%02X) @%s", dev.name, dev.addr, link.name)
        dev.last_seen = now
        dev.online = True
        dev.link_name = link.name
        self.ring.push("in", link.name, frame)

        if frame.type == MSG_ID_HEARTBEAT and len(frame.payload) >= 4:
            dev.battery_mv, dev.link_quality, dev.flags = struct.unpack("<HBb", frame.payload[:4])
        elif frame.type == MSG_ID_TELEMETRY_SAMPLE and len(frame.payload) >= 5:
            var_id, value = struct.unpack("<Bf", frame.payload[:5])
            self.hub.update(frame.src, var_id, value, now)
        elif frame.type == MSG_ID_DEBUG_ECHO and frame.src != ADDR_PC and not frame.payload.startswith(b"ack:"):
            # "ack:" 前缀 = 对端对我方 Probe 的应答，不再回显，否则形成回声风暴
            asyncio.get_running_loop().create_task(self._echo_reply(frame, link))

    # -- 出向 ---------------------------------------------------------------
    async def send(self, link: "LinkDriver", msg_type: int, payload: bytes, dst: int, seq: int | None = None) -> None:
        if seq is None:
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            seq = self._tx_seq
        frame = Frame(src=ADDR_PC, type=msg_type, seq=seq, payload=payload)
        self.ring.push("out", link.name, frame)
        await link.send_frame(frame, dst)

    async def _echo_reply(self, frame: Frame, link: "LinkDriver") -> None:
        await self.send(link, MSG_ID_DEBUG_ECHO, b"ack:" + frame.payload[:64], dst=frame.src, seq=frame.seq)

    async def probe_echo(self, dst: int, payload: bytes) -> bool:
        link = self.link_for_device(dst)
        if link is None:
            return False
        await self.send(link, MSG_ID_DEBUG_ECHO, payload, dst=dst)
        return True

    def link_for_device(self, addr: int) -> "LinkDriver | None":
        dev = self.devices.get(addr)
        return self.links.get(dev.link_name) if dev else None

    # -- 维护 ----------------------------------------------------------------
    async def lease_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            now = time.time()
            for dev in self.devices.values():
                dev.online = (now - dev.last_seen) < self.HEARTBEAT_TIMEOUT

    def snapshot(self) -> list[dict]:
        return [dev.to_dict(self.hub) for dev in sorted(self.devices.values(), key=lambda d: d.addr)]
