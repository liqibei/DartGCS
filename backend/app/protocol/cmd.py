"""CMD 命令码常量与号段（协议草案 v0.2 §4）。

号段按设备分块：0x1xxx 飞镖 / 0x2xxx 镖架 / 0x3xxx 基地 / 0x0xxx 系统与主机 / 0x0Exx 调试。
参数与变量监视在三个设备块内语义同构，用块基址 + 子段偏移生成，PC 端解码保持通用。
"""
from __future__ import annotations

from dataclasses import dataclass

# ---- 系统与主机管理（全体，0x0xxx）----
SYS_HEARTBEAT = 0x0001
SYS_TIME_SYNC = 0x0002
SYS_PROBE = 0x0003
SYS_REBOOT = 0x0004
SYS_FW_VERSION = 0x0005
SYS_HOST_STATS = 0x0010

# ---- 调试（全体，0x0Exx）----
DBG_ECHO = 0x0E00
DBG_PRINT = 0x0E01

# ---- 设备块基址 ----
BLOCK_DART = 0x1000
BLOCK_LAUNCHER = 0x2000
BLOCK_BASE = 0x3000

# 块内子段偏移
SUB_PARAM = 0x000  # x0xx 参数服务
SUB_VAR = 0x100    # x1xx 变量监视
SUB_FUNC = 0x200   # x2xx 设备专属控制
SUB_STATE = 0x300  # x3xx 模式与状态


@dataclass(frozen=True, slots=True)
class BlockCmds:
    """一个设备块的通用命令组（参数 + 变量监视），语义三设备同构。"""

    base: int

    @property
    def catalog_get(self) -> int:
        return self.base + SUB_PARAM + 0x00

    @property
    def catalog_rsp(self) -> int:
        return self.base + SUB_PARAM + 0x01

    @property
    def read(self) -> int:
        return self.base + SUB_PARAM + 0x02

    @property
    def read_rsp(self) -> int:
        return self.base + SUB_PARAM + 0x03

    @property
    def write(self) -> int:
        return self.base + SUB_PARAM + 0x04

    @property
    def write_rsp(self) -> int:
        return self.base + SUB_PARAM + 0x05

    @property
    def save(self) -> int:
        return self.base + SUB_PARAM + 0x06

    @property
    def reset(self) -> int:
        return self.base + SUB_PARAM + 0x07

    @property
    def var_catalog_get(self) -> int:
        return self.base + SUB_VAR + 0x00

    @property
    def var_catalog_rsp(self) -> int:
        return self.base + SUB_VAR + 0x01

    @property
    def var_subscribe(self) -> int:
        return self.base + SUB_VAR + 0x02

    @property
    def var_unsubscribe(self) -> int:
        return self.base + SUB_VAR + 0x03

    @property
    def var_samples(self) -> int:
        return self.base + SUB_VAR + 0x10


BLOCKS = {
    "dart": BlockCmds(BLOCK_DART),
    "launcher": BlockCmds(BLOCK_LAUNCHER),
    "base": BlockCmds(BLOCK_BASE),
}

# ---- 飞行日志（飞镖块 0x12xx）----
LOG_INFO_GET = BLOCK_DART + SUB_FUNC + 0x00
LOG_INFO_RSP = BLOCK_DART + SUB_FUNC + 0x01
LOG_CHUNK_REQ = BLOCK_DART + SUB_FUNC + 0x02
LOG_CHUNK = BLOCK_DART + SUB_FUNC + 0x03
LOG_ERASE = BLOCK_DART + SUB_FUNC + 0x04

# ---- 镖架专属（0x22xx / 0x23xx）----
LAUNCH_SINGLE = BLOCK_LAUNCHER + 0x201
LAUNCH_FOUR = BLOCK_LAUNCHER + 0x202
LAUNCH_ABORT = BLOCK_LAUNCHER + 0x203
LAUNCH_RESULT = BLOCK_LAUNCHER + 0x204  # 发射执行结果（应答）
LAUNCHER_MODE = BLOCK_LAUNCHER + 0x301
LAUNCHER_STATE = BLOCK_LAUNCHER + 0x311

# ---- 基地专属（0x32xx / 0x33xx）----
BASE_MODE = BLOCK_BASE + 0x201
BASE_TARGET = BLOCK_BASE + 0x202
BASE_RUN = BLOCK_BASE + 0x203
BASE_STATE = BLOCK_BASE + 0x311

# ---- 应答配对表：请求 CMD → 应答 CMD ----
# （匹配键 = (源ID, 应答CMD)；SEQ 由待应答队列校验，详见 devices/manager.py）
RESPONSE_OF: dict[int, int] = {}


def _bind_block(base: int) -> None:
    RESPONSE_OF.update(
        {
            base + SUB_PARAM + 0x00: base + SUB_PARAM + 0x01,  # catalog
            base + SUB_PARAM + 0x02: base + SUB_PARAM + 0x03,  # read
            base + SUB_PARAM + 0x04: base + SUB_PARAM + 0x05,  # write
            base + SUB_PARAM + 0x06: base + SUB_PARAM + 0x05,  # save → 通用结果
            base + SUB_PARAM + 0x07: base + SUB_PARAM + 0x05,  # reset → 通用结果
            base + SUB_VAR + 0x00: base + SUB_VAR + 0x01,      # var catalog
            base + SUB_VAR + 0x02: base + SUB_VAR + 0x02,      # subscribe 原值应答
            base + SUB_VAR + 0x03: base + SUB_VAR + 0x03,      # unsubscribe 原值应答
        }
    )


_bind_block(BLOCK_DART)
_bind_block(BLOCK_LAUNCHER)
_bind_block(BLOCK_BASE)
RESPONSE_OF.update(
    {
        SYS_PROBE: SYS_PROBE,
        DBG_ECHO: DBG_ECHO,
        SYS_REBOOT: SYS_REBOOT,
        SYS_FW_VERSION: SYS_FW_VERSION,
        LOG_INFO_GET: LOG_INFO_RSP,
        LOG_CHUNK_REQ: LOG_CHUNK,
        LOG_ERASE: LOG_CHUNK,  # 复用块应答（DATA 回带日志ID+块号=0xFFFF 表示完成）
        LAUNCH_SINGLE: LAUNCH_RESULT,
        LAUNCH_FOUR: LAUNCH_RESULT,
        LAUNCH_ABORT: LAUNCH_RESULT,
        LAUNCHER_MODE: LAUNCHER_MODE,  # 空=读，带载荷=写并原值应答
        BASE_MODE: BASE_MODE,
        BASE_TARGET: BASE_TARGET,
        BASE_RUN: BASE_RUN,
    }
)


def response_of(cmd: int) -> int | None:
    return RESPONSE_OF.get(cmd)


# ---- 数据面帧（参与 SEQ 丢帧统计的 CMD 集合）----
DATA_PLANE_CMDS = {
    SYS_HEARTBEAT,
    SYS_HOST_STATS,
    LAUNCHER_STATE,
    BASE_STATE,
    *(blk.base + SUB_VAR + 0x10 for blk in BLOCKS.values()),
}
