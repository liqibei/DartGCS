"""REST API。

约定：路径里的 dev_id 为十进制设备 ID（0x31 = 49）；参数值为 JSON 数值/布尔，
按目录声明的类型编码为 8B 槽位下行。
"""
from __future__ import annotations

import struct
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")


class ProbeIn(BaseModel):
    dst: int = Field(description="目标设备 ID，如 49 = 0x31")
    payload_hex: str = ""


class ParamWriteIn(BaseModel):
    param_id: int
    value: float | int | bool


class VarSubIn(BaseModel):
    items: list[dict] = Field(default_factory=list)  # [{id, rate}]


class VarUnsubIn(BaseModel):
    ids: list[int] = Field(default_factory=list)


class LaunchIn(BaseModel):
    slot: int = Field(ge=1, le=4)
    force: float
    pitch: float
    yaw: float = 0.0


class ModeIn(BaseModel):
    mode: int


class TargetIn(BaseModel):
    pos: float


class RunIn(BaseModel):
    run: int


class SessionIn(BaseModel):
    dart_addr: int
    notes: str = ""
    params: dict = Field(default_factory=dict)


class SessionPatch(BaseModel):
    notes: str | None = None
    refs: dict | None = None


def _svc(request: Request, name: str):
    return getattr(request.app.state, name)


@router.get("/health")
def health(request: Request):
    state = request.app.state
    online = sum(1 for d in state.manager.devices.values() if d.online)
    return {"ok": True, "name": "dart-gcs", "proto": "v0.2",
            "uptime_s": round(time.time() - state.started_at, 1), "devices_online": online}


@router.get("/devices")
def devices(request: Request):
    return request.app.state.manager.snapshot()


@router.get("/frames")
def frames(request: Request, limit: int = 200):
    return request.app.state.ring.recent(min(limit, 500))


@router.post("/probe/echo")
async def probe_echo(request: Request, body: ProbeIn):
    payload = bytes.fromhex(body.payload_hex) if body.payload_hex else b""
    try:
        rsp = await _svc(request, "manager").request(
            body.dst, 0x0E00, payload, timeout=0.3, retries=1
        )
    except Exception as exc:
        raise HTTPException(504, str(exc)) from exc
    return {"ok": True, "payload_hex": rsp.payload.hex()}


# ---- 参数服务 ------------------------------------------------------------
@router.get("/devices/{dev_id}/params")
async def device_params(request: Request, dev_id: int, refresh: bool = False):
    try:
        return await _svc(request, "params").read_all(dev_id)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/devices/{dev_id}/params/refresh")
async def device_params_refresh(request: Request, dev_id: int):
    try:
        entries = await _svc(request, "params").get_catalog(dev_id, refresh=True)
        return {"count": len(entries)}
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/devices/{dev_id}/params/write")
async def device_param_write(request: Request, dev_id: int, body: ParamWriteIn):
    try:
        code = await _svc(request, "params").write(dev_id, body.param_id, body.value)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    if code != 0:
        raise HTTPException(409, f"写入被拒绝，结果码 {code}")
    return {"ok": True}


@router.post("/devices/{dev_id}/params/save")
async def device_param_save(request: Request, dev_id: int):
    return {"result": await _svc(request, "params").save(dev_id)}


@router.post("/devices/{dev_id}/params/reset")
async def device_param_reset(request: Request, dev_id: int):
    return {"result": await _svc(request, "params").reset(dev_id)}


# ---- 变量监视 ------------------------------------------------------------
@router.get("/devices/{dev_id}/vars")
async def device_vars(request: Request, dev_id: int):
    entries = await _svc(request, "monitor").get_catalog(dev_id)
    subs = _svc(request, "monitor").subscriptions(dev_id)
    return [{"id": e.vid, "name": e.name, "unit": e.unit, "rate": e.rate,
             "subscribed": subs.get(e.vid)} for e in entries]


@router.post("/devices/{dev_id}/vars/subscribe")
async def device_vars_subscribe(request: Request, dev_id: int, body: VarSubIn):
    try:
        await _svc(request, "monitor").subscribe(dev_id, body.items)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "subscriptions": _svc(request, "monitor").subscriptions(dev_id)}


@router.post("/devices/{dev_id}/vars/unsubscribe")
async def device_vars_unsubscribe(request: Request, dev_id: int, body: VarUnsubIn):
    await _svc(request, "monitor").unsubscribe(dev_id, body.ids)
    return {"ok": True}


# ---- 飞行日志 ------------------------------------------------------------
@router.get("/devices/{dev_id}/logs")
async def device_logs(request: Request, dev_id: int):
    try:
        return await _svc(request, "logs").list_logs(dev_id)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/devices/{dev_id}/logs/{log_id}")
async def device_log_pull(request: Request, dev_id: int, log_id: int):
    try:
        data = await _svc(request, "logs").pull(dev_id, log_id)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    # 关联：若该飞镖有最近的发次归档，则把日志挂进 manifest
    archive = _svc(request, "archive")
    sid = getattr(request.app.state, "last_session_by_dart", {}).get(dev_id)
    if sid:
        archive.update(sid, refs={"csv": f"dart{dev_id:02X}/log{log_id}"})
    return {"id": log_id, "size": len(data), "text": data.decode("utf-8", errors="replace")}


@router.post("/devices/{dev_id}/logs/erase")
async def device_log_erase(request: Request, dev_id: int, body: dict):
    try:
        await _svc(request, "logs").erase(dev_id, int(body.get("log_id", 1)))
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}


# ---- 镖架 ----------------------------------------------------------------
@router.post("/launcher/launch")
async def launcher_launch(request: Request, body: LaunchIn):
    payload = struct.pack("<Bfff", body.slot, body.force, body.pitch, body.yaw)
    try:
        rsp = await _svc(request, "manager").request(0x10, 0x2201, payload, timeout=0.5)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    code, slot = rsp.payload[0], rsp.payload[1]
    if code != 0:
        raise HTTPException(409, f"发射被拒绝，结果码 {code}")
    # 发次归档：自动记录发射参数快照，供后续关联飞行日志
    _svc(request, "archive").create(
        dart_addr=0x30 | (body.slot - 1),
        params={"slot": body.slot, "force": body.force,
                "pitch": body.pitch, "yaw": body.yaw},
        notes="",
    )
    state = request.app.state
    state.last_session_by_dart[0x30 | (body.slot - 1)] = archive_list_latest(state)
    return {"ok": True, "slot": slot}


def archive_list_latest(state):
    sessions = state.archive.list()
    return sessions[0]["id"] if sessions else None


@router.post("/launcher/four")
async def launcher_four(request: Request):
    try:
        rsp = await _svc(request, "manager").request(0x10, 0x2202, b"", timeout=0.5)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": rsp.payload[0] == 0, "code": rsp.payload[0], "slot": rsp.payload[1]}


@router.post("/launcher/abort")
async def launcher_abort(request: Request):
    try:
        rsp = await _svc(request, "manager").request(0x10, 0x2203, b"", timeout=0.5)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": rsp.payload[0] == 0}


@router.post("/launcher/mode")
async def launcher_mode(request: Request, body: ModeIn):
    try:
        await _svc(request, "manager").request(0x10, 0x2301, bytes([body.mode]))
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "mode": body.mode}


# ---- 基地 ----------------------------------------------------------------
@router.post("/base/mode")
async def base_mode(request: Request, body: ModeIn):
    try:
        await _svc(request, "manager").request(0x20, 0x3201, bytes([body.mode]))
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "mode": body.mode}


@router.post("/base/target")
async def base_target(request: Request, body: TargetIn):
    try:
        await _svc(request, "manager").request(
            0x20, 0x3202, struct.pack("<f", body.pos)
        )
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "pos": body.pos}


@router.post("/base/run")
async def base_run(request: Request, body: RunIn):
    try:
        await _svc(request, "manager").request(0x20, 0x3203, bytes([body.run]))
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "run": body.run}


# ---- 发次归档 ------------------------------------------------------------
@router.get("/sessions")
def sessions(request: Request):
    return request.app.state.archive.list()


@router.post("/sessions")
def create_session(request: Request, body: SessionIn):
    return request.app.state.archive.create(body.dart_addr, body.params, body.notes)


@router.patch("/sessions/{sid}")
def patch_session(request: Request, sid: str, body: SessionPatch):
    manifest = request.app.state.archive.update(sid, notes=body.notes, refs=body.refs)
    if manifest is None:
        raise HTTPException(404, "发次不存在")
    return manifest
