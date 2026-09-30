"""协议帧编解码（协议草案 v0.2）。

    [SOF 0xA5][LEN 2B][SEQ 1B][CRC8 1B] | [ID 1B][CMD 2B][DATA n] | [CRC16 2B]

- CRC8 覆盖 SOF+LEN+SEQ（帧头），CRC16 整包覆盖 SOF..DATA；全小端
- 整帧 ≤ 250 字节（ESP-NOW 单包上限），DATA ≤ 240
- ID 方向语义：下行帧 = 目的设备，上行帧 = 源设备；PC 为隐含端点
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .crc import crc16, crc8

SOF = 0xA5
HEADER_LEN = 5  # SOF LEN(2) SEQ CRC8
OVERHEAD = HEADER_LEN + 1 + 2 + 2  # + ID + CMD + CRC16
MAX_FRAME = 250
DATA_MAX = MAX_FRAME - OVERHEAD

# 设备 ID（协议草案 §2）
ID_LAUNCHER = 0x10
ID_BASE = 0x20
ID_HOST = 0xFE
ID_BROADCAST = 0xFF
ID_PC = None  # 隐含端点


def dart_id(n: int) -> int:
    return 0x30 | ((n - 1) & 0x0F)


def kind_of_id(dev_id: int) -> str:
    hi = dev_id & 0xF0
    if hi == 0x10:
        return "launcher"
    if hi == 0x20:
        return "base"
    if hi == 0x30:
        return "dart"
    if dev_id == ID_HOST:
        return "host"
    return "unknown"


def device_name(dev_id: int) -> str:
    kind = kind_of_id(dev_id)
    if kind == "launcher":
        return "LAUNCHER"
    if kind == "base":
        return "BASE"
    if kind == "dart":
        return f"DART-{(dev_id & 0x0F) + 1:02d}"
    if kind == "host":
        return "C3-HOST"
    return f"0x{dev_id:02X}"


@dataclass(slots=True)
class Frame:
    id: int
    cmd: int
    seq: int
    payload: bytes


def build_frame(cmd: int, data: bytes, dev_id: int, seq: int) -> bytes:
    if len(data) > DATA_MAX:
        raise ValueError(f"DATA {len(data)}B 超出上限 {DATA_MAX}B")
    head = struct.pack("<BHB", SOF, len(data), seq & 0xFF)
    head += bytes([crc8(head)])
    body = head + struct.pack("<BH", dev_id, cmd) + data
    return body + struct.pack("<H", crc16(body))


class FrameParser:
    """流式解析：串口字节流与整包皆可；校验失败丢弃 1 字节重新同步。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self._buf += data
        frames: list[Frame] = []
        while True:
            i = self._buf.find(bytes([SOF]))
            if i < 0:
                if len(self._buf) > 3:  # SOF 单字节，保留尾部即可
                    del self._buf[:-3]
                break
            if i > 0:
                del self._buf[:i]
            if len(self._buf) < HEADER_LEN:
                break
            length = struct.unpack("<H", self._buf[1:3])[0]
            if length > DATA_MAX or crc8(bytes(self._buf[:4])) != self._buf[4]:
                del self._buf[:1]
                continue
            total = HEADER_LEN + 3 + length + 2
            if len(self._buf) < total:
                break
            body = bytes(self._buf[: total - 2])
            (crc_val,) = struct.unpack("<H", self._buf[total - 2 : total])
            if crc16(body) != crc_val:
                del self._buf[:1]
                continue
            dev_id = self._buf[5]
            (cmd,) = struct.unpack("<H", self._buf[6:8])
            payload = bytes(self._buf[8 : 8 + length])
            frames.append(Frame(id=dev_id, cmd=cmd, seq=self._buf[3], payload=payload))
            del self._buf[:total]
        return frames
