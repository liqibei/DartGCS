"""参数/变量值与目录条目的线格式编解码（协议草案 §6/§7）。

值统一按 8B 槽位传输（小端，右侧补零）；类型由目录条目声明。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

# 类型编码（目录条目 type 字节）
F32, U8, U16, U32, I16, I32, BOOL = 0, 1, 2, 3, 4, 5, 6

_FMT = {F32: "<f", U8: "<B", U16: "<H", U32: "<I", I16: "<h", I32: "<i", BOOL: "<?"}

PARAM_ENTRY = struct.Struct("<H8sB6s")  # ID + 名称8 + 类型 + 单位6（min/max/默认另计 24B）
VAR_ENTRY = struct.Struct("<B8s6sB")    # ID + 名称8 + 单位6 + 建议频率


def pack_value(type_code: int, value) -> bytes:
    if type_code in (U8, U16, U32, I16, I32):
        value = int(round(value))
    raw = struct.pack(_FMT[type_code], bool(value) if type_code == BOOL else value)
    return raw.ljust(8, b"\x00")


def unpack_value(type_code: int, slot: bytes):
    fmt = _FMT[type_code]
    size = struct.calcsize(fmt)
    v = struct.unpack(fmt, slot[:size])[0]
    return bool(v) if type_code == BOOL else v


def _cstr(b: bytes) -> str:
    return b.split(b"\x00", 1)[0].decode("ascii", errors="replace")


@dataclass(slots=True)
class ParamEntry:
    pid: int
    name: str
    type: int
    unit: str
    vmin: float
    vmax: float
    default: float

    @classmethod
    def decode(cls, raw: bytes) -> "ParamEntry":
        pid, name, t, unit = PARAM_ENTRY.unpack_from(raw, 0)
        mn, mx, df = struct.unpack_from("<8s8s8s", raw, 17)
        return cls(pid, _cstr(name), t, _cstr(unit),
                   unpack_value(t, mn), unpack_value(t, mx), unpack_value(t, df))

    def encode(self) -> bytes:
        return (
            PARAM_ENTRY.pack(self.pid, self.name.encode()[:8].ljust(8), self.type,
                             self.unit.encode()[:6].ljust(6))
            + pack_value(self.type, self.vmin)
            + pack_value(self.type, self.vmax)
            + pack_value(self.type, self.default)
        )


@dataclass(slots=True)
class VarEntry:
    vid: int
    name: str
    unit: str
    rate: int

    @classmethod
    def decode(cls, raw: bytes) -> "VarEntry":
        vid, name, unit, rate = VAR_ENTRY.unpack(raw)
        return cls(vid, _cstr(name), _cstr(unit), rate)

    def encode(self) -> bytes:
        return VAR_ENTRY.pack(self.vid, self.name.encode()[:8].ljust(8),
                              self.unit.encode()[:6].ljust(6), self.rate)
