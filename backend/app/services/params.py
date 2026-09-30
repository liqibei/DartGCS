"""参数服务：目录自描述的 PC 侧实现。

固件注册参数表 → PC 分页拉取目录缓存 → 读写/保存/恢复出厂全部走
待应答队列（超时重发、新 SEQ）。因为参数"具体没定、数量多"，
协议与界面都不写死任何参数——目录里有什么，界面就长什么。
"""
from __future__ import annotations

import struct

from ..protocol import BlockCmds, build_frame  # noqa: F401  (build_frame 供测试对照)
from ..protocol.cmd import BLOCKS
from ..protocol.value import ParamEntry, pack_value, unpack_value
from ..devices.device import DeviceKind

_CATALOG_PAGE_ENTRIES = 5


class ParamError(Exception):
    pass


class ParamService:
    def __init__(self, manager) -> None:
        self.manager = manager
        self._catalogs: dict[int, list[ParamEntry]] = {}

    @staticmethod
    def _block(dev_id: int) -> BlockCmds:
        kind = DeviceKind(kind_of_id_compat(dev_id))
        return BLOCKS[kind.value]

    async def get_catalog(self, dev_id: int, refresh: bool = False) -> list[ParamEntry]:
        if dev_id in self._catalogs and not refresh:
            return self._catalogs[dev_id]
        block = self._block(dev_id)
        entries: list[ParamEntry] = []
        page = 0
        for _ in range(100):  # 防御：目录异常时不无限拉
            rsp = await self.manager.request(dev_id, block.catalog_get,
                                             struct.pack("<H", page))
            page_no, total = struct.unpack_from("<HH", rsp.payload, 0)
            body = rsp.payload[4:]
            for off in range(0, len(body) - len(body) % 41, 41):
                entries.append(ParamEntry.decode(body[off : off + 41]))
            if len(entries) >= total or not body:
                break
            page += 1
        self._catalogs[dev_id] = entries
        return entries

    async def read(self, dev_id: int, param_id: int) -> tuple[float, float]:
        """返回 (已存值, 当前值)。"""
        block = self._block(dev_id)
        rsp = await self.manager.request(dev_id, block.read, struct.pack("<H", param_id))
        entry = await self._entry_of(dev_id, param_id)
        saved = unpack_value(entry.type, rsp.payload[2:10])
        current = unpack_value(entry.type, rsp.payload[10:18])
        return saved, current

    async def read_all(self, dev_id: int) -> list[dict]:
        entries = await self.get_catalog(dev_id)
        out = []
        for e in entries:
            saved, current = await self.read(dev_id, e.pid)
            out.append({
                "id": e.pid, "name": e.name, "type": e.type, "unit": e.unit,
                "min": e.vmin, "max": e.vmax, "default": e.default,
                "saved": saved, "current": current,
                "modified": abs(current - saved) > 1e-9,
            })
        return out

    async def write(self, dev_id: int, param_id: int, value) -> int:
        block = self._block(dev_id)
        entry = await self._entry_of(dev_id, param_id)
        rsp = await self.manager.request(
            dev_id, block.write, struct.pack("<H", param_id) + pack_value(entry.type, value)
        )
        return rsp.payload[2]

    async def save(self, dev_id: int) -> int:
        block = self._block(dev_id)
        rsp = await self.manager.request(dev_id, block.save, b"")
        return rsp.payload[2]

    async def reset(self, dev_id: int) -> int:
        block = self._block(dev_id)
        rsp = await self.manager.request(dev_id, block.reset, b"")
        return rsp.payload[2]

    async def _entry_of(self, dev_id: int, param_id: int) -> ParamEntry:
        for e in await self.get_catalog(dev_id):
            if e.pid == param_id:
                return e
        raise ParamError(f"参数 0x{param_id:04X} 不在目录中")


def kind_of_id_compat(dev_id: int) -> str:
    from ..protocol.frame import kind_of_id

    return kind_of_id(dev_id)
