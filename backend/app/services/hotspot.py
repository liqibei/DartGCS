"""手机控制：同一局域网直访 + 一键热点备用。

首选"同一局域网"：后端默认监听 0.0.0.0，电脑连手机热点/路由器/现场 AP，
手机进同一网络即可访问——本服务自动探测本机局域网 IP 并给出访问地址。
一键热点（Linux nmcli / Windows 移动热点，scripts/hotspot_win.ps1）只作为
现场无任何网络的备用手段，占用无线网卡会断开现有 Wi-Fi。命令差异封装在本模块，
REST 层与前端无感知。子进程统一放线程池执行（Windows 下 Selector 事件循环不支持
asyncio 子进程，且串口兼容策略也要求避免切换回 Proactor）。
"""
from __future__ import annotations

import asyncio
import platform
import shutil
import socket
import subprocess

SSID_DEFAULT = "dart-gcs"
PASSWORD_DEFAULT = "dart2027"
# nmcli 热点默认网关；Windows 移动热点默认网关
URL_BY_OS = {"Linux": "http://10.42.0.1:8787", "Windows": "http://192.168.137.1:8787"}


def lan_ips() -> list[str]:
    """本机所有非回环 IPv4；第一个通常是默认路由所在网段（即手机该访问的地址）。"""
    ips: list[str] = []
    try:  # 默认路由地址（不实际发包，仅查路由表）
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


class HotspotService:
    def __init__(self, ssid: str = SSID_DEFAULT, password: str = PASSWORD_DEFAULT,
                 *, exposed: bool = True, port: int = 8787) -> None:
        self.ssid = ssid
        self.password = password
        self.exposed = exposed  # 后端是否监听 0.0.0.0（否则局域网访问不可用）
        self.port = port
        self._lock = asyncio.Lock()  # 防止连点并发改系统状态

    # ---- 基础 ----
    @property
    def available(self) -> bool:
        if platform.system() == "Linux":
            return shutil.which("nmcli") is not None and self._wifi_iface() is not None
        if platform.system() == "Windows":
            return True
        return False

    @property
    def url(self) -> str:
        return URL_BY_OS.get(platform.system(), "http://127.0.0.1:8787")

    def lan_urls(self) -> list[str]:
        if not self.exposed:
            return []
        return [f"http://{ip}:{self.port}" for ip in lan_ips()]

    @staticmethod
    def _run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

    async def _arun(self, cmd: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
        return await asyncio.to_thread(self._run, cmd, timeout)

    def _wifi_iface(self) -> str | None:
        try:
            rc, out, _ = self._run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"], 10)
            if rc != 0:
                return None
            for line in out.splitlines():
                dev, typ = line.split(":")[:2]
                if typ == "wifi" and not dev.startswith("p2p"):
                    return dev
        except Exception:
            return None
        return None

    # ---- 状态 ----
    async def status(self) -> dict:
        s = {"lan_urls": self.lan_urls(),
             "lan_hint": ("" if self.exposed else "后端仅监听本机（DART_GCS_HOST=127.0.0.1），手机无法访问")}
        if not self.available:
            s.update({"available": False, "active": False, "ssid": "", "url": self.url,
                      "hint": "本机无 nmcli/无线网卡，无法开热点（同一局域网访问不受影响）"})
            return s
        if platform.system() == "Linux":
            s.update(await self._status_linux())
        else:
            s.update(await self._run_ps("status"))
        return s

    async def _status_linux(self) -> dict:
        rc, out, _ = await self._arun(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"], 10)
        iface = self._wifi_iface()
        if rc == 0:
            for line in out.splitlines():
                parts = line.split(":")
                if len(parts) >= 3 and parts[1] == "802-11-wireless-hotspot":
                    return {"available": True, "active": True, "ssid": self.ssid,
                            "url": self.url, "hint": f"热点运行中（{parts[2]}）"}
        return {"available": True, "active": False, "ssid": self.ssid,
                "url": self.url, "hint": f"开启将占用无线网卡 {iface or '?'} 并断开现有 Wi-Fi"}

    async def _run_ps(self, action: str) -> dict:
        """Windows：调用移动热点 PowerShell 脚本（on/off/status）。"""
        from pathlib import Path
        script = Path(__file__).resolve().parents[1] / "scripts" / "hotspot_win.ps1"
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(script), "-Action", action]
        try:
            rc, out, err = await self._arun(cmd, 45)
        except Exception as exc:
            return {"available": False, "active": False, "ssid": self.ssid,
                    "url": self.url, "hint": f"执行失败：{exc}"}
        active = "STATE:On" in out or "STATE:InTransition" in out and action == "on"
        if rc != 0 or "ERROR:" in out:
            hint = (out.split("ERROR:")[-1] or err or "未知错误").strip()
            return {"available": True, "active": False, "ssid": self.ssid,
                    "url": self.url, "hint": f"Windows 移动热点：{hint}"}
        return {"available": True, "active": bool(active), "ssid": self.ssid,
                "url": self.url,
                "hint": ("热点运行中" if active else "移动热点未开启")}

    # ---- 开关 ----
    async def set_enabled(self, on: bool) -> dict:
        async with self._lock:
            if not self.available:
                return await self.status()
            if on:
                return await self._enable_linux() if platform.system() == "Linux" \
                    else await self._run_ps("on")
            return await self._disable_linux() if platform.system() == "Linux" \
                else await self._run_ps("off")

    async def _enable_linux(self) -> dict:
        iface = self._wifi_iface()
        if iface is None:
            return {"available": False, "active": False, "ssid": self.ssid,
                    "url": self.url, "hint": "未找到无线网卡"}
        cmd = ["nmcli", "device", "wifi", "hotspot", "ifname", iface,
               "ssid", self.ssid, "password", self.password, "band", "a"]
        try:
            rc, out, err = await self._arun(cmd, 40)
        except subprocess.TimeoutExpired:
            return {"available": True, "active": False, "ssid": self.ssid, "url": self.url,
                    "hint": "开启超时（网卡可能不支持 AP/5G 频段，试试去掉 band a）"}
        if rc != 0:
            hint = (err or out).strip().splitlines()[-1] if (err or out).strip() else "开启失败"
            return {"available": True, "active": False, "ssid": self.ssid, "url": self.url,
                    "hint": hint}
        return await self._status_linux()

    async def _disable_linux(self) -> dict:
        # 找到活动热点连接名再 down
        rc, out, _ = await self._arun(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"], 10)
        if rc == 0:
            for line in out.splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[1] == "802-11-wireless-hotspot":
                    await self._arun(["nmcli", "connection", "down", "id", parts[0]], 20)
        return await self._status_linux()
