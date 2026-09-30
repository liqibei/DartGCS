"""运行配置：全部可用环境变量覆盖，便于台架/赛场切换。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_list(name: str) -> list[str]:
    return [p for p in os.getenv(name, "").replace(",", " ").split() if p]


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    api_port: int = 8787
    udp_port: int = 7756  # 无线帧统一入口：STA 设备与 ESP-NOW 桥接守护进程均投递到此
    tcp_port: int = 7757  # 设备 TCP 直连（台架调参）
    serial_ports: list[str] = field(default_factory=list)  # USB：台架直连 / C3 桥接
    data_root: Path = Path("data")
    enable_mock: bool = True  # 仿真设备开关，无硬件开发/演示用

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("DART_GCS_HOST", "127.0.0.1"),
            api_port=int(os.getenv("DART_GCS_API_PORT", "8787")),
            udp_port=int(os.getenv("DART_GCS_UDP_PORT", "7756")),
            tcp_port=int(os.getenv("DART_GCS_TCP_PORT", "7757")),
            serial_ports=_env_list("DART_GCS_SERIAL"),
            data_root=Path(os.getenv("DART_GCS_DATA", "data")),
            enable_mock=os.getenv("DART_GCS_MOCK", "1") != "0",
        )
