"""帧编解码单元测试：协议栈是全系统的契约，这里必须先于硬件可靠。"""
import pytest

from app.protocol.frame import (
    PAYLOAD_MAX,
    FrameParser,
    build_frame,
    dart_addr,
    kind_of_addr,
)


def test_roundtrip():
    data = build_frame(0x01, b"\x01\x02\x03", src=0x31, seq=7)
    frames = FrameParser().feed(data)
    assert len(frames) == 1
    f = frames[0]
    assert (f.src, f.type, f.seq, f.payload) == (0x31, 0x01, 7, b"\x01\x02\x03")


def test_stream_split_across_feeds():
    data = build_frame(0x90, b"\x01\x02\x03\x04\x05", src=0x31, seq=1)
    parser = FrameParser()
    assert parser.feed(data[:3]) == []
    assert parser.feed(data[3:9]) == []
    frames = parser.feed(data[9:])
    assert len(frames) == 1 and frames[0].type == 0x90


def test_two_frames_one_datagram():
    a = build_frame(0x01, b"a", src=0x20, seq=0)
    b = build_frame(0x01, b"bb", src=0x31, seq=1)
    frames = FrameParser().feed(a + b)
    assert [f.src for f in frames] == [0x20, 0x31]


def test_garbage_prefix():
    good = build_frame(0x01, b"x", src=0x20, seq=2)
    frames = FrameParser().feed(b"\x00\x13\x37\x00" + good)
    assert len(frames) == 1 and frames[0].payload == b"x"


def test_bad_crc_resync():
    good = build_frame(0x90, b"12345678", src=0x31, seq=3)
    bad = bytearray(build_frame(0x90, b"12345678", src=0x31, seq=3))
    bad[-1] ^= 0xFF
    frames = FrameParser().feed(bytes(bad) + good)
    assert len(frames) == 1 and frames[0].payload == b"12345678"


def test_fake_header_resync():
    # Ver 非法 -> 应跳过假帧头找到真帧
    good = build_frame(0x01, b"y", src=0x20, seq=4)
    fake = b"\xaa\x55\x09\x01\x00\x01\x20"
    frames = FrameParser().feed(fake + good)
    assert len(frames) == 1


def test_payload_limit():
    with pytest.raises(ValueError):
        build_frame(0x01, b"\x00" * (PAYLOAD_MAX + 1), src=0x31, seq=0)


def test_addr_scheme():
    assert kind_of_addr(dart_addr(3)) == "dart"
    assert kind_of_addr(0x20) == "base"
    assert kind_of_addr(0x10) == "launcher"
    assert kind_of_addr(0xF0) == "pc"
