"""发次归档：一个发次一个目录 + manifest.json。

刻意不用单个大数据库：目录结构可整体拷贝/同步，后续把数据迁到 MiniPC
只需更换 data_root；manifest.json 是每个发次的自描述索引。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_SID_RE = re.compile(r"^launch_\d{8}_\d{6}(_\d+)?$")


class SessionArchive:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, dart_addr: int, params: dict | None = None, notes: str = "") -> dict:
        stamp = datetime.now().strftime("launch_%Y%m%d_%H%M%S")
        d = self.root / stamp
        n = 1
        while d.exists():
            n += 1
            d = self.root / f"{stamp}_{n}"
        d.mkdir(parents=True)
        manifest = {
            "id": d.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dart_addr": dart_addr,
            "params": params or {},
            "notes": notes,
            "refs": {"video": None, "csv": None},
        }
        (d / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest

    def list(self) -> list[dict]:
        out: list[dict] = []
        for d in sorted(self.root.iterdir(), reverse=True):
            mf = d / "manifest.json"
            if d.is_dir() and mf.exists():
                try:
                    out.append(json.loads(mf.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    continue
        return out

    def update(self, sid: str, notes: str | None = None, refs: dict | None = None) -> dict | None:
        if not _SID_RE.match(sid):
            return None
        mf = self.root / sid / "manifest.json"
        if not mf.exists():
            return None
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        if notes is not None:
            manifest["notes"] = notes
        if refs:
            manifest["refs"].update(refs)
        mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest
