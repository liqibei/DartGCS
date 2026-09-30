import { useEffect, useState } from "react";
import { getJSON, postJSON } from "../api/client";
import { useDevices } from "../live/LiveContext";
import type { FrameLogEntry } from "../types";

/** 协议诊断页：原始帧抓包 + Probe 手动发帧（参考 RM Studio 的调试思路）。 */
export default function Diagnostics() {
  const { devices } = useDevices();
  const [frames, setFrames] = useState<FrameLogEntry[]>([]);
  const [dst, setDst] = useState("");
  const [payload, setPayload] = useState("");
  const [msg, setMsg] = useState("");
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    let alive = true;
    const tick = async () => {
      try {
        const f = await getJSON<FrameLogEntry[]>("/api/frames?limit=120");
        if (alive) setFrames(f);
      } catch {
        // 后端未启动时静默
      }
    };
    tick();
    const t = setInterval(tick, 800);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [paused]);

  const sendProbe = async () => {
    setPaused(true); // 冻结列表以便观察回显帧
    try {
      await postJSON("/api/probe/echo", { dst: parseInt(dst, 16), payload_hex: payload });
      const f = await getJSON<FrameLogEntry[]>("/api/frames?limit=120");
      setFrames(f); // 补拉一次，确保 Probe 与 ack 帧进入冻结视图
      setMsg("已发送，列表已暂停；对照 ↓收 的 DEBUG_ECHO ack 验证链路");
    } catch (e) {
      setMsg(`发送失败：${e}`);
    }
  };

  return (
    <div className="page">
      <h2>协议调试</h2>
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-head">
          <b>Probe 回显</b>
          <span className="muted">DEBUG_ECHO → 设备原样回 ack，用于链路探测</span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <select value={dst} onChange={(e) => setDst(e.target.value)}>
            <option value="">选择设备…</option>
            {devices.map((d) => (
              <option key={d.id} value={d.id.toString(16)}>
                {d.name} (0x{d.id.toString(16).padStart(2, "0")})
              </option>
            ))}
          </select>
          <input
            placeholder="payload hex，如 cafe"
            value={payload}
            onChange={(e) => setPayload(e.target.value)}
          />
          <button onClick={sendProbe} disabled={!dst}>
            发送
          </button>
          <button onClick={() => setPaused((p) => !p)}>
            {paused ? "继续滚动" : "暂停滚动"}
          </button>
          <span className="muted">{msg}</span>
        </div>
      </div>
      <table className="frames">
        <thead>
          <tr>
            <th>时间</th>
            <th>方向</th>
            <th>链路</th>
            <th>源</th>
            <th>消息</th>
            <th>面</th>
            <th>长度</th>
            <th>Payload (hex)</th>
          </tr>
        </thead>
        <tbody>
          {frames
            .slice()
            .reverse()
            .map((f, i) => (
              <tr key={i}>
                <td className="muted">{new Date(f.ts * 1000).toLocaleTimeString()}</td>
                <td className={f.dir === "in" ? "dir-in" : "dir-out"}>
                  {f.dir === "in" ? "↓ 收" : "↑ 发"}
                </td>
                <td>{f.link}</td>
                <td>{f.src}</td>
                <td>{f.type}</td>
                <td className="muted">{f.plane}</td>
                <td>{f.len}B</td>
                <td className="hex">{f.hex}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
