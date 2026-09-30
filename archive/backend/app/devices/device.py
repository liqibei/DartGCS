"""设备模型：地址 -> 类型/名称/在线状态。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeviceKind(str, Enum):
    LAUNCHER = "launcher"
    BASE = "base"
    DART = "dart"
    UNKNOWN = "unknown"


def kind_of_addr(addr: int) -> DeviceKind:
    hi = addr & 0xF0
    if hi == 0x10:
        return DeviceKind.LAUNCHER
    if hi == 0x20:
        return DeviceKind.BASE
    if hi == 0x30:
        return DeviceKind.DART
    return DeviceKind.UNKNOWN


def device_name(addr: int) -> str:
    kind = kind_of_addr(addr)
    if kind is DeviceKind.LAUNCHER:
        return "LAUNCHER"
    if kind is DeviceKind.BASE:
        return "BASE"
    if kind is DeviceKind.DART:
        return f"DART-{addr & 0x0F:02d}"
    return f"0x{addr:02X}"


@dataclass(slots=True)
class Device:
    addr: int
    kind: DeviceKind
    name: str
    first_seen: float
    last_seen: float
    battery_mv: int = 0
    link_quality: int = -1
    flags: int = 0
    link_name: str = ""
    online: bool = True

    def to_dict(self, hub) -> dict:
        return {
            "addr": self.addr,
            "kind": self.kind.value,
            "name": self.name,
            "online": self.online,
            "battery_mv": self.battery_mv,
            "link_quality": self.link_quality,
            "link_name": self.link_name,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "telemetry": hub.snapshot(self.addr),
        }
