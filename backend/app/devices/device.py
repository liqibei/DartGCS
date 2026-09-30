"""设备模型：身份 + 心跳租约 + 数据面 SEQ 丢帧统计 + 重启检测。

数据面帧（心跳/采样/状态）使用设备自己的数据计数器；应答帧复用请求 SEQ，
因此丢帧统计只对 DATA_PLANE_CMDS 过滤后进行，避免应答帧破坏连续性。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..protocol.frame import device_name, kind_of_id
from ..protocol.cmd import DATA_PLANE_CMDS
from enum import Enum


class DeviceKind(str, Enum):
    LAUNCHER = "launcher"
    BASE = "base"
    DART = "dart"
    HOST = "host"
    UNKNOWN = "unknown"


def kind_of(dev_id: int) -> DeviceKind:
    return DeviceKind(kind_of_id(dev_id))


@dataclass(slots=True)
class Device:
    id: int
    first_seen: float
    last_seen: float
    kind: DeviceKind = field(default_factory=lambda: DeviceKind.UNKNOWN)
    name: str = ""
    battery_mv: int = 0
    flags: int = 0
    link_name: str = ""
    online: bool = True
    # SEQ 对账
    _last_data_seq: int | None = None
    rx_count: int = 0
    loss_count: int = 0
    reboot_count: int = 0

    def __post_init__(self) -> None:
        if not self.kind or self.kind is DeviceKind.UNKNOWN:
            self.kind = kind_of(self.id)
        if not self.name:
            self.name = device_name(self.id)

    def on_data_frame(self, seq: int) -> None:
        """数据面帧对账：连续=正常，跳号=丢帧，回绕异常=疑似重启。"""
        self.rx_count += 1
        if self._last_data_seq is None:
            self._last_data_seq = seq
            return
        diff = (seq - self._last_data_seq) & 0xFF
        if diff == 0:
            return  # 重复帧，不计丢帧
        if diff > 127:  # 回跳：重启或计数异常
            self.reboot_count += 1
            self._last_data_seq = seq
            return
        self.loss_count += diff - 1
        self._last_data_seq = seq

    @property
    def loss_rate(self) -> float:
        total = self.rx_count + self.loss_count
        return round(self.loss_count / total, 4) if total else 0.0

    def to_dict(self, hub) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "online": self.online,
            "battery_mv": self.battery_mv,
            "loss_rate": self.loss_rate,
            "reboot_count": self.reboot_count,
            "link_name": self.link_name,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "telemetry": hub.snapshot(self.id),
        }
