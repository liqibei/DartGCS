"""协议帧编解码。

帧格式（整帧 <= 250 字节，受 ESP-NOW 单包 250B 上限约束）：

    [AA 55][Ver][Type][Seq][Len][SrcAddr][Payload...][CRC_L][CRC_H]

- Len：Payload 字节数（<= 241）
- CRC16/CCITT-FALSE：覆盖 Ver..Payload
- SrcAddr：发送方设备地址，高半字节为设备类型（见下方地址表）
- 下行多镖寻址（多镖共用桥接节点时的 DstAddr）在协议草案中补充；
  当前单链路场景以"学习到的对端"回发。

地址方案（草案，协议冻结时复核）：
  0x10 发射架   0x20 基地   0x3N 飞镖 N   0xF0 上位机
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

SOF = b"\xaa\x55"
VER = 1
HEADER_LEN = 7  # AA 55 Ver Type Seq Len SrcAddr
FRAME_OVERHEAD = HEADER_LEN + 2
MAX_FRAME = 250
PAYLOAD_MAX = MAX_FRAME - FRAME_OVERHEAD

ADDR_PC = 0xF0
ADDR_LAUNCHER = 0x10
ADDR_BASE = 0x20


def dart_addr(n: int) -> int:
    return 0x30 | (n & 0x0F)


def kind_of_addr(addr: int) -> str:
    hi = addr & 0xF0
    if hi == 0x10:
        return "launcher"
    if hi == 0x20:
        return "base"
    if hi == 0x30:
        return "dart"
    if addr == ADDR_PC:
        return "pc"
    return "unknown"


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        crc &= 0xFFFF
    return crc


@dataclass(slots=True)
class Frame:
    src: int
    type: int
    seq: int
    payload: bytes
    ver: int = VER


def build_frame(msg_type: int, payload: bytes, src: int, seq: int, ver: int = VER) -> bytes:
    if len(payload) > PAYLOAD_MAX:
        raise ValueError(f"payload {len(payload)}B 超出上限 {PAYLOAD_MAX}B")
    body = struct.pack("<BBBBB", ver, msg_type, seq & 0xFF, len(payload), src) + payload
    return SOF + body + struct.pack("<H", crc16_ccitt(body))


class FrameParser:
    """流式解析：兼容串口/TCP 字节流与 UDP 整包；坏帧丢弃后从下一字节重新同步。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self._buf += data
        frames: list[Frame] = []
        while True:
            i = self._buf.find(SOF)
            if i < 0:
                # 最多保留 1 字节尾部：SOF 为两字节，再多不可能构成帧头
                if len(self._buf) > 1:
                    del self._buf[:-1]
                break
            if i > 0:
                del self._buf[:i]
            if len(self._buf) < HEADER_LEN:
                break
            ver, msg_type, seq, plen, src = struct.unpack("<BBBBB", self._buf[2:HEADER_LEN])
            if ver != VER or plen > PAYLOAD_MAX:
                del self._buf[:1]
                continue
            total = HEADER_LEN + plen + 2
            if len(self._buf) < total:
                break
            body = bytes(self._buf[2 : HEADER_LEN + plen])
            (crc,) = struct.unpack("<H", self._buf[HEADER_LEN + plen : total])
            if crc16_ccitt(body) != crc:
                del self._buf[:1]
                continue
            payload = bytes(self._buf[HEADER_LEN : HEADER_LEN + plen])
            frames.append(Frame(src=src, type=msg_type, seq=seq, payload=payload))
            del self._buf[:total]
        return frames
