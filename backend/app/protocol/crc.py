"""CRC 校验——算法与 RoboMaster 裁判系统附录一官方实现逐位一致。

CRC8 : 多项式 x^8+x^5+x^4+1（反射实现，反射值 0x8C），初值 0xFF，用于帧头
CRC16: 多项式 x^16+x^12+x^5+1（反射实现，反射值 0x8408），初值 0xFFFF，用于整包

查找表按官方 C 代码的位算法在导入时生成，单元测试用官方表格前几项锚定，
保证与 STM32/C3 侧照抄的官方 C 代码逐位兼容。
"""


def _make_table8(poly_reflected: int) -> list[int]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = ((crc >> 1) ^ poly_reflected) if (crc & 1) else (crc >> 1)
        table.append(crc)
    return table


def _make_table16(poly_reflected: int) -> list[int]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = ((crc >> 1) ^ poly_reflected) if (crc & 1) else (crc >> 1)
        table.append(crc & 0xFFFF)
    return table


_CRC8_TAB = _make_table8(0x8C)
_CRC16_TAB = _make_table16(0x8408)

CRC8_INIT = 0xFF
CRC16_INIT = 0xFFFF


def crc8(data: bytes, init: int = CRC8_INIT) -> int:
    crc = init
    for byte in data:
        crc = _CRC8_TAB[crc ^ byte]
    return crc


def crc16(data: bytes, init: int = CRC16_INIT) -> int:
    crc = init
    for byte in data:
        crc = ((crc >> 8) & 0xFF) ^ _CRC16_TAB[(crc ^ byte) & 0xFF]
    return crc & 0xFFFF
