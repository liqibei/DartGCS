"""消息号段划分与注册表（占位版）。

号段规划（协议草案冻结后在此逐条登记消息与 payload 结构，固件侧共用同一契约）：
  0x00-0x0F 系统：心跳 / 时间同步 / 模式切换
  0x10-0x3F 参数（控制面）：catalog / GET / SET / SAVE / COMMIT
  0x40-0x6F 任务：发射指令 / 运动模式 / 联锁自检
  0x70-0x8F 文件：CSV 日志读回 / 录像清单 / 分块传输
  0x90-0xEF 遥测（数据面）
  0xF0-0xFE 调试：Probe / 原始回显
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MessageDef:
    id: int
    name: str
    plane: str  # control / data / debug
    note: str = ""


MSG_ID_HEARTBEAT = 0x01
MSG_ID_TELEMETRY_SAMPLE = 0x90
MSG_ID_DEBUG_ECHO = 0xF0

MSG_HEARTBEAT = MessageDef(MSG_ID_HEARTBEAT, "HEARTBEAT", "control", "电池mV(u16) + 链路质量(u8) + flags(u8)")
MSG_TELEMETRY_SAMPLE = MessageDef(MSG_ID_TELEMETRY_SAMPLE, "TELEMETRY_SAMPLE", "data", "变量id(u8) + fp32")
MSG_DEBUG_ECHO = MessageDef(MSG_ID_DEBUG_ECHO, "DEBUG_ECHO", "debug", "payload 原样回显，用于链路探测")

REGISTRY: dict[int, MessageDef] = {m.id: m for m in (MSG_HEARTBEAT, MSG_TELEMETRY_SAMPLE, MSG_DEBUG_ECHO)}


def describe(msg_id: int) -> MessageDef | None:
    return REGISTRY.get(msg_id)


def plane_of(msg_id: int) -> str:
    if 0x90 <= msg_id <= 0xEF:
        return "data"
    if msg_id >= 0xF0:
        return "debug"
    return "control"
