# Dart GCS — 飞镖调参上位机

RMUC 2027 飞镖系统的调参/监控/回放上位机。Web 前后端架构，当前为 **P0 框架阶段**：
链路层、协议栈、设备管理、遥测管线、发次归档已打通，Mock 仿真设备可无硬件运行全流程。

## 系统架构

```
                ┌── 以太网 ── MiniPC（RK3588S：双相机 H.264 推流 + 图像识别，另行开发）
PC（本仓库）────┤
 GCS 后端+前端  ├─ USB ── C3 ×1（ESP-NOW 桥接节点：只收实飞遥测）
                └─ WiFi AP（2.4G）←— STA/TCP —— 基地 C3、飞镖 C3、发射架 C3
飞镖/基地/发射架 = STM32 主控 + C3 链路模块（统一固件，角色参数区分）
```

设计约定（详见会话记录）：控制链路全部收口在 PC；视频永远不过 C3；2.4G 信道锁死；
发次归档"一发次一目录 + manifest.json"（可整体迁移到 MiniPC，开发期先落 PC）。

## 目录结构

```
Upper/
├── backend/               # FastAPI 后端
│   ├── app/
│   │   ├── links/         # 链路层：Udp / Tcp / Serial / Mock 四驱动
│   │   ├── protocol/      # 帧编解码（AA55/Ver/Type/Seq/Len/Src/Payload/CRC16，≤250B）
│   │   │                  # + 消息注册表（号段划分，协议草案冻结后在此扩展）
│   │   ├── devices/       # 设备管理：心跳租约、单一 RX Owner 帧分发、帧环形缓冲
│   │   ├── services/      # 遥测枢纽（10Hz 批推）、发次归档
│   │   ├── api/           # REST + WebSocket
│   │   └── main.py        # 入口：组装链路/服务，托管前端 dist
│   └── tests/             # 帧编解码单元测试（协议栈是全系统契约）
├── frontend/              # React + Vite + TS
│   └── src/pages/         # 总览 / 发射架 / 基地 / 飞镖 / 回放分析 / 协议调试
└── data/sessions/         # 发次归档（运行时生成）
```

## 快速启动

两个系统都能跑：Ubuntu/Debian（含 RK3588）与 Windows。差异只有启动命令和串口名。

```bash
# 后端（首次，两平台相同）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # Windows: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt

# 启动 —— Ubuntu（含 Mock 仿真设备，浏览器打开 http://127.0.0.1:8787）
.venv/bin/python -m uvicorn app.main:app --port 8787
# 启动 —— Windows（必须走本入口：UDP 需要 Selector 事件循环，代码已在 main.py 顶部自动切换）
.venv\Scripts\python -m app.main

# 前端（改动后需重新构建，产物由后端托管）
cd frontend && npm install && npm run build

# 前端热更开发（另开终端，代理到后端）
cd frontend && npm run dev

# 测试
cd backend && .venv/bin/python -m pytest tests -q
```

平台差异速查：

| 事项 | Ubuntu / RK3588 | Windows |
|---|---|---|
| 后端启动 | `uvicorn app.main:app` 或 `python -m app.main` | **只能 `python -m app.main`** |
| 串口名（`DART_GCS_SERIAL`） | `/dev/ttyUSB0`、`/dev/ttyACM0` | `COM5` 等 |
| 开 WiFi AP（给 C3 设备连） | hostapd | 系统"移动热点"（系统网络功能，与本仓库代码无关） |
| 打包交付 | PyInstaller 生成 Linux 二进制 | PyInstaller 生成 .exe（各自平台打包，不能交叉） |

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DART_GCS_API_PORT` | 8787 | 后端/整站端口 |
| `DART_GCS_UDP_PORT` | 7756 | 无线帧统一入口（STA 设备 + ESP-NOW 桥接守护进程） |
| `DART_GCS_TCP_PORT` | 7757 | 设备 TCP 直连（C3 为客户端连入） |
| `DART_GCS_SERIAL` | 空 | 逗号分隔串口列表（台架 USB / C3 桥接虚拟串口） |
| `DART_GCS_DATA` | data | 归档根目录 |
| `DART_GCS_MOCK` | 1 | 仿真设备开关（接真硬件前置 0） |

## 已实现（P0 框架）

- 帧编解码 + 流式解析（坏帧重同步）+ CRC16/CCITT-FALSE，8 个单测
- 四链路驱动 + 对端学习 + 单一 RX Owner 分发
- 设备表：按地址推断类型（0x10 发射架 / 0x20 基地 / 0x3N 飞镖）、心跳租约 3s 掉线
- 遥测枢纽：最新值缓存 + 100ms 批量 WS 推送（采样/渲染分离）
- 协议调试页：原始帧抓包 + Probe 回显（发送后自动冻结列表）+ 暂停/继续
- 发次归档：目录 + manifest.json（params 快照 / notes / video+csv 引用）
- Mock 链路：发射架/基地/双飞镖仿真，心跳 2Hz + 遥测 20Hz，电池缓降

## 路线图

- **P1** 发射架页：双相机 WHEP 拉流（mediamtx 部署在 MiniPC）、一镖一参 ×4、内录管理、发射联锁自检（触发装置 ≥4V）
- **P2** 飞镖页：编号分配、参数注册表动态表单（三层生命周期 Default/Saved/Session + 写策略在 MCU 裁决）、订阅制遥测示波、CSV 日志读回；基地页：四档运动模式
- **P3** 回放分析：CSV 校验 → three.js 3D 轨迹 + 录像同轴联动
- **P4** 编队视图 / OTA / 数据自动归档到 MiniPC

## 与固件的契约

`app/protocol/` 是三方（STM32 固件、C3 固件、GCS）共用的编解码参考实现。
协议草案冻结前只有帧层 + 三个占位消息（HEARTBEAT / TELEMETRY_SAMPLE / DEBUG_ECHO）；
冻结后按 `registry.py` 的号段规划逐条登记，C 侧编解码库由同一份 schema 生成。
