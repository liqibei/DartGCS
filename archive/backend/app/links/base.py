"""链路驱动基类。

链路层只做字节搬运：传输实现调用 feed_bytes()，基类负责切帧并回调 on_frame。
send_frame(frame, dst) 统一出口：组帧后交给子类 send_raw()。
对端学习：UDP/TCP 按收帧来源记录地址（src -> peer），下行按 dst 回发。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from ..protocol.frame import Frame, FrameParser, build_frame

logger = logging.getLogger(__name__)

# on_frame(frame, link) 必须是同步函数：保证同链路帧序，异步动作由接收方自行 create_task
FrameHandler = Callable[[Frame, "LinkDriver"], None]


class LinkDriver:
    def __init__(self, name: str) -> None:
        self.name = name
        self.on_frame: FrameHandler | None = None
        self._parser = FrameParser()
        self._tasks: list[asyncio.Task] = []
        self._peers: dict[int, object] = {}  # src addr -> 传输层对端
        self._last_peer: object = None

    # -- 入向 -------------------------------------------------------------
    def feed_bytes(self, chunk: bytes, peer: object = None) -> None:
        for frame in self._parser.feed(chunk):
            if peer is not None:
                self._peers[frame.src] = peer
                self._last_peer = peer
            if self.on_frame is not None:
                try:
                    self.on_frame(frame, self)
                except Exception:  # 单帧处理异常不应中断链路
                    logger.exception("处理来自 %s 的帧时出错 (type=0x%02X)", self.name, frame.type)

    # -- 出向 -------------------------------------------------------------
    async def send_frame(self, frame: Frame, dst: int | None = None) -> None:
        data = build_frame(frame.type, frame.payload, frame.src, frame.seq, frame.ver)
        await self.send_raw(data, dst)

    async def send_raw(self, data: bytes, dst: int | None = None) -> None:
        raise NotImplementedError

    def _peer_for(self, dst: int | None) -> object | None:
        if dst is not None and dst in self._peers:
            return self._peers[dst]
        return self._last_peer  # 未学到的地址回发到最近对端（单设备链路场景）

    # -- 生命周期 ----------------------------------------------------------
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        return task
