"""变量监视服务：目录自描述 + 订阅制采样。

PC 订阅 {变量ID: 频率}，从机只发被订阅变量；采样帧由 manager 分发到
on_samples，解析后进遥测枢纽批量推送前端。
"""
from __future__ import annotations

import struct

from ..devices.device import DeviceKind
from ..protocol.cmd import BLOCKS
from ..protocol.value import VarEntry


class MonitorService:
    def __init__(self, manager, hub) -> None:
        self.manager = manager
        self.hub = hub
        self._catalogs: dict[int, list[VarEntry]] = {}
        self._subs: dict[int, dict[int, int]] = {}
        manager.sample_listener = self.on_samples

    @staticmethod
    def _block(dev_id: int) -> "BlockCmds":
        kind = DeviceKind(_kind_of_id(dev_id))
        return BLOCKS[kind.value]

    async def get_catalog(self, dev_id: int, refresh: bool = False) -> list[VarEntry]:
        if dev_id in self._catalogs and not refresh:
            return self._catalogs[dev_id]
        block = self._block(dev_id)
        entries: list[VarEntry] = []
        page = 0
        for _ in range(50):
            rsp = await self.manager.request(dev_id, block.var_catalog_get,
                                             struct.pack("<H", page))
            _, total = struct.unpack_from("<HH", rsp.payload, 0)
            body = rsp.payload[4:]
            for off in range(0, len(body) - len(body) % 16, 16):
                entries.append(VarEntry.decode(body[off : off + 16]))
            if len(entries) >= total or not body:
                break
            page += 1
        self._catalogs[dev_id] = entries
        return entries

    async def subscribe(self, dev_id: int, items: list[dict]) -> None:
        """items: [{id: int, rate: int}]"""
        await self.get_catalog(dev_id)
        payload = struct.pack("<B", len(items)) + b"".join(
            struct.pack("<BB", int(i["id"]), int(i["rate"])) for i in items
        )
        await self.manager.request(dev_id, self._block(dev_id).var_subscribe, payload)
        self._subs.setdefault(dev_id, {}).update({int(i["id"]): int(i["rate"]) for i in items})

    async def unsubscribe(self, dev_id: int, ids: list[int]) -> None:
        payload = struct.pack("<B", len(ids)) + bytes(int(i) for i in ids)
        await self.manager.request(dev_id, self._block(dev_id).var_unsubscribe, payload)
        subs = self._subs.get(dev_id, {})
        for i in ids:
            subs.pop(int(i), None)

    def subscriptions(self, dev_id: int) -> dict[int, int]:
        return dict(self._subs.get(dev_id, {}))

    def on_samples(self, dev_id: int, payload: bytes) -> None:
        ts = _now()
        for off in range(0, len(payload) - len(payload) % 5, 5):
            vid, value = struct.unpack_from("<Bf", payload, off)
            self.hub.update(dev_id, vid, value, ts)


def _now() -> float:
    import time

    return time.time()


def _kind_of_id(dev_id: int) -> str:
    from ..protocol.frame import kind_of_id

    return kind_of_id(dev_id)
