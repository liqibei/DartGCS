"""遥测枢纽：最新值缓存 + 待推送批次。

订阅制（变量目录/频率协商）由 monitor 服务实现；本枢纽只负责
"采集 -> 最新值 -> WS 批量推送"，批推间隔 100ms（采样率与渲染率分离）。
"""
from __future__ import annotations

from dataclasses import dataclass

VAR_NAMES: dict[int, str] = {
    1: "height_m",
    2: "speed_ms",
    3: "pitch_deg",
    4: "roll_deg",
    5: "yaw_deg",
}


@dataclass(slots=True)
class Sample:
    var: int
    name: str
    value: float
    ts: float


class TelemetryHub:
    def __init__(self) -> None:
        self._latest: dict[tuple[int, int], Sample] = {}
        self._pending: list[dict] = []

    def update(self, addr: int, var_id: int, value: float, ts: float,
               name: str | None = None) -> None:
        sample = Sample(var_id, name or VAR_NAMES.get(var_id, f"var{var_id}"), value, ts)
        self._latest[(addr, var_id)] = sample
        self._pending.append(
            {"addr": addr, "var": var_id, "name": sample.name, "value": round(value, 4), "ts": ts}
        )

    def take_pending(self) -> list[dict]:
        pending = self._pending
        self._pending = []
        return pending

    def snapshot(self, addr: int) -> list[dict]:
        return [
            {"var": s.var, "name": s.name, "value": round(s.value, 4), "ts": s.ts}
            for (a, _), s in sorted(self._latest.items())
            if a == addr
        ]
