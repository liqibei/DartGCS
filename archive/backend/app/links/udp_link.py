"""UDP 链路：无线帧统一入口。

STA 设备（基地/台架飞镖/发射架 C3）与 ESP-NOW 桥接守护进程均以 UDP 投递到
本端口；一个数据报一帧或多帧均可（解析器自适应）。
"""
from __future__ import annotations

import asyncio
import logging

from .base import LinkDriver

logger = logging.getLogger(__name__)


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, link: "UdpLink") -> None:
        self._link = link

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        self._link.feed_bytes(data, peer=addr)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UDP 链路错误: %s", exc)


class UdpLink(LinkDriver):
    def __init__(self, name: str, port: int) -> None:
        super().__init__(name)
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self), local_addr=("0.0.0.0", self.port)
        )
        logger.info("UDP 链路监听 :%d", self.port)

    async def stop(self) -> None:
        await super().stop()
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def send_raw(self, data: bytes, dst: int | None = None) -> None:
        peer = self._peer_for(dst)
        if self._transport is None or peer is None:
            logger.debug("UDP 下行丢弃（无对端 dst=%s）", dst)
            return
        self._transport.sendto(data, peer)
