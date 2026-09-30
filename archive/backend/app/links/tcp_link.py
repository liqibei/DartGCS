"""TCP 链路：设备主动连入（PC 是 TCP 服务端，C3 的 STA 固件按此约定实现）。"""
from __future__ import annotations

import asyncio
import logging

from .base import LinkDriver

logger = logging.getLogger(__name__)


class _Conn:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    def write(self, data: bytes) -> None:
        self.writer.write(data)


class TcpLink(LinkDriver):
    def __init__(self, name: str, port: int) -> None:
        super().__init__(name)
        self.port = port
        self._server: asyncio.Server | None = None
        self._conns: set[_Conn] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._on_client, "0.0.0.0", self.port)
        logger.info("TCP 链路监听 :%d", self.port)

    async def stop(self) -> None:
        await super().stop()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn = _Conn(reader, writer)
        self._conns.add(conn)
        peer = writer.get_extra_info("peername")
        logger.info("TCP 设备接入 %s", peer)
        try:
            while chunk := await reader.read(4096):
                self.feed_bytes(chunk, peer=conn)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            self._conns.discard(conn)
            self._peers = {a: c for a, c in self._peers.items() if c is not conn}
            writer.close()
            logger.info("TCP 设备断开 %s", peer)

    async def send_raw(self, data: bytes, dst: int | None = None) -> None:
        conn = self._peer_for(dst)
        if conn is None:
            logger.debug("TCP 下行丢弃（无对端 dst=%s）", dst)
            return
        conn.write(data)
