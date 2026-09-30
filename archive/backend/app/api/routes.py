"""REST API。"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")


class ProbeIn(BaseModel):
    dst: int = Field(description="目标设备地址，如 0x31")
    payload_hex: str = ""


class SessionIn(BaseModel):
    dart_addr: int
    notes: str = ""
    params: dict = Field(default_factory=dict)


class SessionPatch(BaseModel):
    notes: str | None = None
    refs: dict | None = None


@router.get("/health")
def health(request: Request):
    state = request.app.state
    online = sum(1 for d in state.manager.devices.values() if d.online)
    return {
        "ok": True,
        "name": "dart-gcs",
        "uptime_s": round(time.time() - state.started_at, 1),
        "devices_online": online,
    }


@router.get("/devices")
def devices(request: Request):
    return request.app.state.manager.snapshot()


@router.get("/frames")
def frames(request: Request, limit: int = 200):
    return request.app.state.ring.recent(min(limit, 500))


@router.post("/probe/echo")
async def probe_echo(request: Request, body: ProbeIn):
    payload = bytes.fromhex(body.payload_hex) if body.payload_hex else b""
    ok = await request.app.state.manager.probe_echo(body.dst, payload)
    if not ok:
        raise HTTPException(404, "目标设备未知或无链路")
    return {"ok": True}


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
