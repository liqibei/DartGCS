"""飞行日志服务：分块拉取（拉动式，PC 控节奏）。

十几 KB 日志 = ~70 块；多镖同时需要日志时由 PC 逐台拉动，天然排队。
"""
from __future__ import annotations

import struct

from ..devices.device import DeviceKind


class LogError(Exception):
    pass


class LogService:
    def __init__(self, manager) -> None:
        self.manager = manager

    async def list_logs(self, dev_id: int) -> list[dict]:
        from ..protocol.cmd import LOG_INFO_GET

        rsp = await self.manager.request(dev_id, LOG_INFO_GET, b"")
        (count,) = struct.unpack_from("<B", rsp.payload, 0)
        out = []
        for i in range(count):
            log_id, size, ts = struct.unpack_from("<BII", rsp.payload, 1 + i * 9)
            out.append({"id": log_id, "size": size, "ts": ts})
        return out

    async def pull(self, dev_id: int, log_id: int, *, chunk_rate_s: float = 0.0) -> bytes:
        """整段拉取：按块号顺序请求，校验总长。"""
        from ..protocol.cmd import LOG_CHUNK, LOG_CHUNK_REQ

        chunks: dict[int, bytes] = {}
        total_chunks: int | None = None
        index = 0
        while total_chunks is None or index < total_chunks:
            rsp = await self.manager.request(
                dev_id, LOG_CHUNK_REQ, struct.pack("<BH", log_id, index), timeout=0.3
            )
            rid, chunk_no, total = struct.unpack_from("<BHH", rsp.payload, 0)
            if rid != log_id or chunk_no != index:
                raise LogError(f"块序错乱：期望 {index}，收到 {chunk_no}")
            total_chunks = total
            chunks[chunk_no] = bytes(rsp.payload[5:])
            index += 1
            if chunk_rate_s:
                await _sleep(chunk_rate_s)
        data = b"".join(chunks[i] for i in range(len(chunks)))
        if total_chunks and len(data) < total_chunks * 232 - 232 + 1 and not data:
            raise LogError("日志为空")
        return data

    async def erase(self, dev_id: int, log_id: int) -> None:
        from ..protocol.cmd import LOG_ERASE

        await self.manager.request(dev_id, LOG_ERASE, struct.pack("<B", log_id))


async def _sleep(s: float) -> None:
    import asyncio

    await asyncio.sleep(s)
