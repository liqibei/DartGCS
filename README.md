# Dart GCS — 飞镖调参上位机

RMUC 2027 飞镖系统的调参/监控/回放上位机。Web 前后端架构，当前为 **P0 框架阶段**：
协议栈（v0.2 草案）、单链路接入、设备管理、参数目录、变量监视、日志拉取、发次归档
全部打通，Mock 仿真设备可无硬件运行全流程。

## 系统拓扑（v0.2，无 AP）

```
                ┌── USB3.0/网线 ── MiniPC（相机画面 + 图像识别，另行开发）
PC（本仓库）────┤
 GCS 后端+前端  └─ USB CDC 串口 ── C3主机 ──┬─ ESP-NOW（同一 RF 信道）── 飞镖 #1~#12 的 C3
                                            └─ 有线 ── 镖架 / 基地 的 C3
所有从机 = STM32 主控 + C3 链路模块；C3 主机为纯中转站（ID→腿 路由）
PC 侧只看见一条 USB 串口；协议帧格式有线/无线完全一致
```

- 协议：`协议草案-v0.2.md`（本目录）——帧格式 `SOF/LEN/SEQ/CRC8 + ID + CMD(2B) + DATA≤240B + CRC16`，
  CRC 算法与官方 C 实现同裁判系统附录一，三方（GCS/C3/STM32）共用该契约
- 相机画面不经过 C3 与本协议，走独立链路

## 目录结构

```
Upper/
├── 协议草案-v0.2.md       # 三方契约（评审中）
├── backend/app/
│   ├── protocol/          # crc(裁判同款) / frame(编解码) / cmd(号段) / value(目录条目编解码)
│   ├── links/             # SerialLink(USB) + MockLink(仿真主机+全部设备)
│   ├── devices/           # 设备表(SEQ丢帧统计/重启检测) + 待应答队列 + 帧环形缓冲
│   ├── services/          # 参数目录 / 变量订阅 / 日志拉取 / 遥测枢纽 / 发次归档
│   └── api/               # REST + WebSocket
├── frontend/              # React + Vite + TS（总览/发射架/基地/飞镖/回放/协议调试）
├── data/sessions/         # 发次归档（一发次一目录 + manifest.json）
└── archive/               # 旧拓扑框架（AP 方案）归档，仅作参考
```

## 快速启动

### 日常使用：一键启动（推荐）

前置条件只有一条：装好 **Python ≥ 3.10**（Windows 安装时勾选 *Add to PATH*）。前端已预构建，不需要 Node/npm。

**Windows**：双击仓库根目录的 `启动上位机.bat`，保持黑窗口开着（关掉窗口即停止上位机）。

**Linux / macOS**：

```bash
./start.sh
```

启动脚本首次运行会自动创建 venv 并联网装依赖（约 1~2 分钟），之后秒启。看到

```
  Dart GCS:  http://127.0.0.1:8787
```

后，浏览器打开 **http://127.0.0.1:8787** 即可使用。默认开启 Mock 仿真设备（12 镖 + 镖架 + 基地全部在线），无硬件也能操作全流程。

**接真实硬件**：先设环境变量再启动——

```bash
# Windows (PowerShell)：$env:DART_GCS_SERIAL="COM5"; $env:DART_GCS_MOCK="0"; .\启动上位机.bat
# Linux：DART_GCS_SERIAL=/dev/ttyACM0 DART_GCS_MOCK=0 ./start.sh
```

**局域网访问**（其他电脑浏览器打开本机页面）：把 `DART_GCS_HOST` 设为 `0.0.0.0`（见下表），其他电脑访问 `http://<本机IP>:8787`。

**常见问题**：
- 端口被占用 → 换 `DART_GCS_API_PORT`（如 `8788`），浏览器地址跟着改
- Linux 串口无权限 → `sudo usermod -aG dialout $USER` 后重新登录
- Windows 双击 bat 闪退 → 多半是没装 Python 或没勾 Add to PATH，命令行里手动跑一次看报错

### 开发者命令

```bash
# 后端（首次）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 启动（含 Mock 仿真，浏览器打开 http://127.0.0.1:8787；必须走 app.main 入口，不要直接 uvicorn）
.venv/bin/python -m app.main                                # Ubuntu
#.venv\Scripts\python -m app.main                            # Windows

# 前端（改动后重新构建，产物由后端托管）
cd frontend && npm install && npm run build

# 测试（帧层锚定官方 CRC 表 + Mock 全流程集成）
cd backend && .venv/bin/python -m pytest tests -q
```

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DART_GCS_SERIAL` | 空 | USB 串口（Linux `/dev/ttyACM0`，Windows `COM5`），设置后接入真实 C3 主机 |
| `DART_GCS_BAUD` | 2000000 | 串口波特率（CDC 下仅形式参数） |
| `DART_GCS_MOCK` | 1 | 仿真设备开关，接真硬件前置 0 |
| `DART_GCS_DATA` | data | 发次归档根目录（后续整体迁到 MiniPC 只改这里） |
| `DART_GCS_HOST` | 127.0.0.1 | 监听地址，设 `0.0.0.0` 允许局域网内其他电脑访问 |
| `DART_GCS_API_PORT` | 8787 | 整站端口 |

## 已实现（对应协议草案 v0.2）

- 帧编解码 + 流式解析（CRC8 帧头校验 + CRC16 整包校验，坏帧重同步），单测用官方表锚定算法
- Serial + Mock 双链路；Mock 实现**全部 CMD 块**（系统/参数/监视/日志/发射/基地）
- 待应答队列：(设备, 应答CMD) 匹配 + SEQ 校验 + 超时重发新 SEQ；每设备串行化
- 数据面 SEQ 对账：丢帧率、重复帧、重启检测，界面上即"丢帧率"字段
- 参数服务：目录分页拉取 → 界面数据全部来自目录（固件加参数，上位机零改动）；双值读写/保存/恢复出厂
- 变量监视：目录 + 订阅制 + 50ms 批量采样帧（只发被订阅变量）
- 日志拉取：分块 + 块序校验，16KB ≈ 70 块 ≈ 2.5s；拉取后自动挂进发次归档
- 镖架：单发/四发/急停/模式，发射联锁（安全模式拒发 STATE_DENIED）、触发装置电压上报
- 基地：四档运动模式、目标位置、启停，位置遥测
- 发次归档：发射自动建档（参数快照），落点/现象为人工备注字段

## 接下来的工作（距离完成的差距）

> 里程碑定义：**M1 = 能上台架联调**（纯软件，可立即开工）；**M2 = 能上赛场**（依赖协议冻结与真机）。
> 建议开工顺序：基地页 → 飞镖参数表单 → 曲线页 → 镖架页 → 打包。

### M1：上位机软件侧（纯软件，不依赖任何人）

- [ ] **基地页**（最简单，先行验证页面模式）：四档模式切换、目标位置输入/滑条、启停按钮、位置实时显示
- [ ] **飞镖页 · 参数表单**：目录驱动动态表单、修改高亮、保存/恢复出厂流、危险参数二次确认
- [ ] **飞镖页 · 变量监视曲线**：多变量同屏曲线（uPlot/echarts）、变量勾选订阅、频率档位、暂停/缩放——调参核心体验
- [ ] **镖架页**：一镖一参槽位编辑（复用参数表单）、单发/四发面板 + 发射联锁自检清单（触发装置电压/在位/编号）、历史发射记录表（落点/现象备注编辑）
- [ ] **回放分析页**：CSV 导入校验 → three.js 3D 轨迹 + 姿态模型 + 时间轴，与录像同轴联动
- [ ] **健壮性**：串口热插拔自动重连、断线恢复后目录重拉/订阅恢复、参数批量读 CMD、12 镖并发带宽实测
- [ ] **打包交付**：PyInstaller 出 Windows exe；MiniPC systemd 常驻（数据迁移 = 改 `DART_GCS_DATA`）

### M2：协议冻结与真机（依赖外部输入）

- [ ] **协议 v1.0 冻结**（草案第 12 节六项）：单发指令字段编码、四发语义、日志 CSV 列、目录条目大小、镖架/基地有线无线、安全状态机档位；冻结时回写"应答按 (设备, 应答CMD) 匹配 + SEQ 校验"的实现细化
- [ ] **C3 主机固件**：ESP-NOW 收发、ID→MAC 学习绑定、透传、链路统计上报（协议已留 0x0010 HOST_STATS）
- [ ] **从机 STM32 固件**：CRC/帧解析/参数存储/变量上报/日志记录（可向上位机要 C 编解码参考实现 + 参数注册表模板，同一份契约）
- [ ] **TIME_SYNC 落地**：回放对轴依赖，当前 Mock 忽略该帧
- [ ] **真机联调**：发射瞬间天线遮挡、12 镖并发实测、电磁干扰下的丢包率基线

### 依赖硬件到位

- [ ] **视频链路**：MiniPC mediamtx + 前端 WHEP 播放器 + 录像管理（架构已留位，纯增量）

### 明确降级

- **OTA 固件升级**：需求未出现，协议仅预留号段不做实现（台架 USB 刷固件够用）；若要做需在协议 v1.0 补方案

## 换一台电脑运行

整站是自包含的：**拷贝整个 `Upper/` 目录**（U 盘/网盘均可）到新电脑即可，前端已构建好（`frontend/dist`），新电脑不需要 Node/npm，只需要 Python ≥ 3.10。

| 拷贝 | 说明 |
|---|---|
| `backend/app`、`backend/requirements.txt`、`frontend/dist` | 必需 |
| `data/` | 要保留历史发次归档就一起拷 |
| `backend/.venv`、`frontend/node_modules`、`archive/` | **不用拷**（venv 与操作系统/路径绑定，新机重建） |

新电脑步骤：

1. 装 Python ≥ 3.10（Windows 从 python.org 装，勾选 Add to PATH）；
2. 双击 `启动上位机.bat`（Windows）或 `./start.sh`（Linux）——脚本首次运行会自动建 venv 装依赖，之后直接启动；
3. 浏览器打开 `http://127.0.0.1:8787`。

接真实硬件：先设 `DART_GCS_SERIAL`（如 `COM5` / `/dev/ttyACM0`）和 `DART_GCS_MOCK=0` 再启动。

**让局域网内其他电脑访问**（操作位/调参位分屏）：把 `DART_GCS_HOST` 设为 `0.0.0.0` 再启动，
其他电脑浏览器访问 `http://<这台机器的IP>:8787`（Windows 首次需放行防火墙）。
注意：只有插着 C3 主机 USB 的那台电脑跑后端，其余电脑当浏览器终端即可。

**免安装交付**（可选）：在目标系统上用 PyInstaller 打包成单个 exe/二进制
（`pip install pyinstaller && pyinstaller --onefile --add-data "../frontend/dist;frontend/dist" backend/app/main.py` 的思路，
Windows 的 exe 必须在 Windows 上打包，不能交叉）。
