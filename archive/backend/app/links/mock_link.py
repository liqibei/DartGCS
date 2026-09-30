"""Mock 链路：进程内仿真设备。

作用：无硬件时打通 编解码 -> 分发 -> 遥测 -> WS -> 前端 全链路，
同时作为前端开发与演示的常驻数据源。仿真帧走真实 build_frame/FrameParser，
即 Mock 验证的正是协议栈本身。
"""
from __future__ import annotations

import asyncio
import logging
import math
import struct
import time

from ..protocol.frame import ADDR_BASE, ADDR_LAUNCHER, ADDR_PC, FrameParser, build_frame, dart_addr
from ..protocol.registry import MSG_ID_DEBUG_ECHO, MSG_ID_HEARTBEAT, MSG_ID_TELEMETRY_SAMPLE
from .base import LinkDriver

logger = logging.getLogger(__name__)


class _SimDevice:
    period_heartbeat = 0.5
    period_telemetry = 0.05  # 20Hz

    def __init__(self, link: "MockLink", addr: int, name: str, vars_fn) -> None:
        self.link = link
        self.addr = addr
        self.name = name
        self.vars_fn = vars_fn
        self.seq = 0

    def _emit(self, msg_type: int, payload: bytes) -> None:
        data = build_frame(msg_type, payload, self.addr, self.seq)
        self.seq = (self.seq + 1) & 0xFF
        self.link.feed_bytes(data)

    async def run(self) -> None:
        t0 = time.monotonic()
        hb_next = tel_next = 0.0
        while True:
            now = time.monotonic()
            t = now - t0
            if now >= hb_next:
                hb_next += self.period_heartbeat
                battery = max(6800, 8100 - int(t * 20))
                self._emit(MSG_ID_HEARTBEAT, struct.pack("<HBb", battery, 95, 0))
            if now >= tel_next:
                tel_next += self.period_telemetry
                for var_id, value in self.vars_fn(t).items():
                    self._emit(MSG_ID_TELEMETRY_SAMPLE, struct.pack("<Bf", var_id, value))
            await asyncio.sleep(0.01)


def _dart_vars(t: float) -> dict[int, float]:
    return {
        1: 20 + 15 * math.sin(0.7 * t),   # height_m
        2: 18 + 4 * math.sin(0.5 * t),    # speed_ms
        3: 35 + 5 * math.sin(0.9 * t),    # pitch_deg
        4: 8 * math.sin(1.3 * t),         # roll_deg
        5: 90 + 20 * math.sin(0.3 * t),   # yaw_deg
    }


def _base_vars(t: float) -> dict[int, float]:
    return {1: 280 * math.sin(0.2 * t)}  # 目标滑块位置 mm


def _launcher_vars(_: float) -> dict[int, float]:
    return {}


class MockLink(LinkDriver):
    def __init__(self, name: str = "mock") -> None:
        super().__init__(name)
        self._downlink = FrameParser()
        self.sims = [
            _SimDevice(self, ADDR_LAUNCHER, "LAUNCHER", _launcher_vars),
            _SimDevice(self, ADDR_BASE, "BASE", _base_vars),
            _SimDevice(self, dart_addr(1), "DART-01", _dart_vars),
            _SimDevice(self, dart_addr(2), "DART-02", _dart_vars),
        ]

    async def start(self) -> None:
        for sim in self.sims:
            self._spawn(sim.run())
        logger.info("Mock 链路启动：%s", [s.name for s in self.sims])

    async def send_raw(self, data: bytes, dst: int | None = None) -> None:
        # 下行帧回灌进解析器；仿真设备对 Probe 回显应答，模拟真实联调
        for frame in self._downlink.feed(data):
            if (
                frame.src == ADDR_PC
                and frame.type == MSG_ID_DEBUG_ECHO
                and not frame.payload.startswith(b"ack:")
            ):
                for sim in self.sims:
                    if dst is None or dst == sim.addr:
                        reply = build_frame(
                            MSG_ID_DEBUG_ECHO, b"ack:" + frame.payload[:64], sim.addr, frame.seq
                        )
                        self.feed_bytes(reply)
