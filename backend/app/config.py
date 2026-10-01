"""运行配置：环境变量覆盖，便于台架/赛场切换。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    # 默认 0.0.0.0：手机/其他电脑连入任一同一网络即可访问（现场工具的常态需求）；
    # 只在本机用时可用 DART_GCS_HOST=127.0.0.1 收回
    host: str = "0.0.0.0"
    api_port: int = 8787
    serial_port: str | None = None  # USB CDC：PC ↔ C3 主机，唯一真实链路
    baud: int = 2_000_000
    data_root: Path = Path("data")
    enable_mock: bool = True  # 仿真设备开关（无硬件开发/演示）

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("DART_GCS_HOST", "0.0.0.0"),
            api_port=int(os.getenv("DART_GCS_API_PORT", "8787")),
            serial_port=os.getenv("DART_GCS_SERIAL") or None,
            baud=int(os.getenv("DART_GCS_BAUD", "2000000")),
            data_root=Path(os.getenv("DART_GCS_DATA", "data")),
            enable_mock=os.getenv("DART_GCS_MOCK", "1") != "0",
        )
