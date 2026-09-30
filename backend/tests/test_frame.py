"""帧层与 CRC 单元测试。

CRC 表用裁判系统附录一官方表格前几项锚定，保证与 STM32/C3 侧照抄的
官方 C 代码逐位兼容。
"""
import pytest

from app.protocol.crc import _CRC8_TAB, _CRC16_TAB, crc8, crc16
from app.protocol.frame import (
    DATA_MAX,
    FrameParser,
    build_frame,
    dart_id,
    device_name,
    kind_of_id,
)


# ---- CRC 与官方表锚定 ------------------------------------------------------
def test_crc8_table_matches_referee_doc():
    assert (_CRC8_TAB[0], _CRC8_TAB[1], _CRC8_TAB[2], _CRC8_TAB[3]) == (0x00, 0x5E, 0xBC, 0xE2)


def test_crc16_table_matches_referee_doc():
    assert (_CRC16_TAB[0], _CRC16_TAB[1], _CRC16_TAB[2], _CRC16_TAB[3]) == (
        0x0000, 0x1189, 0x2312, 0x329B)


def test_crc8_crc16_are_deterministic():
    data = b"\xa5\x0a\x01\x02\x03"
    assert crc8(data) == crc8(data)
    assert crc16(data) == crc16(data)


# ---- 帧编解码 --------------------------------------------------------------
def test_roundtrip():
    data = build_frame(0x1002, b"\x01\x00", dev_id=dart_id(1), seq=7)
    frames = FrameParser().feed(data)
    assert len(frames) == 1
    f = frames[0]
    assert (f.id, f.cmd, f.seq, f.payload) == (dart_id(1), 0x1002, 7, b"\x01\x00")


def test_stream_split_across_feeds():
    data = build_frame(0x1102, b"\x01\x32", dev_id=dart_id(2), seq=1)
    parser = FrameParser()
    assert parser.feed(data[:3]) == []
    assert parser.feed(data[3:9]) == []
    frames = parser.feed(data[9:])
    assert len(frames) == 1 and frames[0].cmd == 0x1102


def test_two_frames_one_stream():
    a = build_frame(0x0001, b"\x10\x27", dev_id=0x20, seq=0)
    b = build_frame(0x1002, b"\x01\x00", dev_id=dart_id(1), seq=1)
    frames = FrameParser().feed(a + b)
    assert [f.id for f in frames] == [0x20, dart_id(1)]


def test_garbage_prefix():
    good = build_frame(0x0003, b"ping", dev_id=0x20, seq=2)
    frames = FrameParser().feed(b"\x00\x13\x37\x00" + good)
    assert len(frames) == 1 and frames[0].payload == b"ping"


def test_bad_crc8_resync():
    good = build_frame(0x1002, b"\x01\x00", dev_id=dart_id(1), seq=3)
    bad = bytearray(build_frame(0x1002, b"\x01\x00", dev_id=dart_id(1), seq=3))
    bad[4] ^= 0xFF  # 帧头 CRC8 损坏
    frames = FrameParser().feed(bytes(bad) + good)
    assert len(frames) == 1 and frames[0].seq == 3


def test_bad_crc16_resync():
    good = build_frame(0x1004, b"\x01\x00" + b"\x00" * 8, dev_id=dart_id(1), seq=3)
    bad = bytearray(good)
    bad[-1] ^= 0xFF  # 整包 CRC16 损坏
    frames = FrameParser().feed(bytes(bad) + good)
    assert len(frames) == 1 and frames[0].cmd == 0x1004


def test_fake_header_resync():
    good = build_frame(0x0001, b"y", dev_id=0x20, seq=4)
    fake = b"\xa5\x05\x00\x01\x00"  # LEN 合法但后续不是真帧
    frames = FrameParser().feed(fake + good)
    assert len(frames) == 1


def test_payload_limit():
    with pytest.raises(ValueError):
        build_frame(0x0001, b"\x00" * (DATA_MAX + 1), dev_id=dart_id(1), seq=0)


def test_id_scheme():
    assert kind_of_id(dart_id(12)) == "dart"
    assert kind_of_id(0x20) == "base"
    assert kind_of_id(0x10) == "launcher"
    assert kind_of_id(0xFE) == "host"
    assert device_name(dart_id(3)) == "DART-03"
