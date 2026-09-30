"""串口链路：USB 场景——台架直连设备，或 ESP-NOW 桥接 C3 的虚拟串口。"""
from __future__ import annotations

import asyncio
import logging

from .base import LinkDriver

logger = logging.getLogger(__name__)

READ_CHUNK = 512


class SerialLink(LinkDriver):
    def __init__(self, name: str, port: str, baudrate: int = 2_000_000) -> None:
        super().__init__(name)
        self.port = port
        self.baudrate = baudrate
        self._ser = None  # serial.Serial

    async def start(self) -> None:
        try:
            import serial  # pyserial 延迟导入：无串口场景不阻塞启动
        except ImportError as exc:
            raise RuntimeError("需要 pyserial：pip install pyserial") from exc
        self._ser = await asyncio.to_thread(
            serial.Serial, self.port, self.baudrate, timeout=0.05
        )
        self._spawn(self._read_loop())
        logger.info("串口链路已打开 %s @%d", self.port, self.baudrate)

    async def _read_loop(self) -> None:
        while True:
            try:
                data = await asyncio.to_thread(self._ser.read, READ_CHUNK)
            except Exception:
                logger.exception("串口 %s 读取失败，链路退出", self.port)
                return
            if data:
                self.feed_bytes(data)

    async def send_raw(self, data: bytes, dst: int | None = None) -> None:
        if self._ser is None:
            return
        try:
            await asyncio.to_thread(self._ser.write, data)
        except Exception:
            logger.exception("串口 %s 写入失败", self.port)
