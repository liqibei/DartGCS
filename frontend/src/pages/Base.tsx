import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "../api/client";
import { useHistory } from "../live/LiveContext";
import { Sparkline } from "../components/Sparkline";
import {
  BASE_ID, STROKE, MODES, PARAM_NAMES, V, useBaseControl, BaseTrack,
  type ParamInfo,
} from "../components/BaseQuick";

/** 基地子页：详细设置（模式 / 目标位置 / 联动 / 参数目录）。基本控制在设备总览卡片，
 *  两处共用 useBaseControl 同一套控制逻辑，自动/手动 选择跨页共享（useCtrlMode）。 */
export default function Base() {
  const { map: history } = useHistory();
  const c = useBaseControl();
  const { running, light, door, cur, tgt, mode, busy, msg, setMsg, act, ctrl, setCtrlMode } = c;

  const [target, setTarget] = useState(0);
  const [speedSel, setSpeedSel] = useState<0 | 1>(0); // 手动速度选择：0=平移 / 1=停止
  const [autolink, setAutolink] = useState(false);
  const [params, setParams] = useState<ParamInfo[] | null>(null);
  const [paramEdits, setParamEdits] = useState<Record<number, string>>({});
  const targetInited = useRef(false);

  useEffect(() => {
    getJSON<{ enabled: boolean }>("/api/base/autolink").then((r) => setAutolink(r.enabled)).catch(() => {});
    getJSON<ParamInfo[]>(`/api/devices/${BASE_ID}/params`).then(setParams).catch(() => {});
  }, []);

  useEffect(() => {
    if (!targetInited.current && tgt != null) {
      targetInited.current = true;
      setTarget(Math.round(tgt));
    }
  }, [tgt]);

  const reloadParams = () =>
    getJSON<ParamInfo[]>(`/api/devices/${BASE_ID}/params`).then(setParams).catch(() => {});

  const writeParam = async (p: ParamInfo) => {
    const raw = paramEdits[p.id] ?? String(p.current);
    const v = Number(raw);
    if (Number.isNaN(v)) {
      setMsg(`${PARAM_NAMES[p.name.trim()] ?? p.name}：不是数字`);
      return;
    }
    const ok = await act(`写入${PARAM_NAMES[p.name.trim()] ?? p.name}`,
      () => postJSON(`/api/devices/${BASE_ID}/params/write`, { param_id: p.id, value: v }));
    if (ok) {
      setParamEdits((m) => ({ ...m, [p.id]: "" }));
      await reloadParams();
    }
  };

  const saveParams = async () => {
    const ok = await act("保存参数", () => postJSON(`/api/devices/${BASE_ID}/params/save`, {}));
    if (ok) await reloadParams();
  };

  const loadParams = async () => {
    // 从 Flash 读取：已存值恢复为当前值（放弃会话修改），输入框回退到恢复后的值
    const ok = await act("从 Flash 读取", () => postJSON(`/api/devices/${BASE_ID}/params/load`, {}));
    if (ok) {
      setParamEdits({});
      await reloadParams();
    }
  };

  const pct = (v: number) => `${((Math.max(-STROKE, Math.min(STROKE, v)) + STROKE) / (2 * STROKE)) * 100}%`;

  return (
    <div className="page">
      <h2>基地</h2>
      <div style={{ display: "flex", gap: 12, rowGap: 4, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
        <span>
          <span className={`dot ${c.base?.online ? "on" : "off"}`} /> {c.base?.online ? "在线" : "离线"}
        </span>
        <span className="muted">
          电池 {c.base?.online && c.base.battery_mv ? (c.base.battery_mv / 1000).toFixed(2) : "--"} V · 丢帧率 {c.base?.loss_rate ?? "--"}
        </span>
        <span className={running ? "dir-in" : "muted"}>{running ? "● 已使能" : "○ 未使能"}</span>
        <span className={door ? "dir-in" : "muted"}>{door ? "指令开启" : "指令停止"}</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className={light ? "seg-on" : ""} disabled={busy !== ""}
            onClick={() => c.setLight(!light)}>
            {light ? "💡 关灯" : "💡 开灯"}
          </button>
          {running
            ? <button className="btn-green" disabled={busy !== ""} onClick={() => c.setRun(false)}
                title="失能=意外保护：断开电机（0x3203 BRUN=0）。急停只停运动，不失能">■ 失能</button>
            : <button className="btn-red" disabled={busy !== ""} onClick={() => c.setRun(true)}
                title="电机使能（0x3203 BRUN=1）">▶ 使能</button>}
        </span>
        <span className="muted">
          {busy && <b className="dir-out">{busy}中… </b>}{msg}
        </span>
      </div>

      <div className="base-grid">
        <section className="card card-pos">
          <div className="card-head"><b>位置</b><span className="muted">BSTATE 20Hz 实时</span></div>
          <div className="pos-hero">
            <div>
              <div className="muted">当前位置</div>
              <div className="big-num">{cur != null ? cur.toFixed(1) : "--"}<small>mm</small></div>
            </div>
            <div>
              <div className="muted">目标位置</div>
              <div className="big-num" style={{ color: "var(--green)" }}>
                {tgt != null ? tgt.toFixed(1) : "--"}<small>mm</small>
              </div>
            </div>
            <div style={{ marginLeft: "auto", display: "flex", gap: 20 }}>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>当前走势</div>
                <Sparkline values={history.get(V.cur) ?? []} width={160} height={30} />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>目标走势</div>
                <Sparkline values={history.get(V.tgt) ?? []} width={160} height={30} />
              </div>
            </div>
          </div>
          <BaseTrack cur={cur} tgt={tgt} big />
          <div className="muted" style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginTop: 6 }}>
            <span>-{STROKE} mm</span><span>0</span><span>+{STROKE} mm</span>
          </div>
        </section>

        <section className="card">
          <div className="card-head"><b>运动控制</b><span className="muted">模式 / 目标位置</span></div>
          <div className="seg-toggle">
            <button className={ctrl === "auto" ? "seg-on" : ""} onClick={() => setCtrlMode("auto")}
              title="基地按预设档位规则自主运动">
              自动模式
            </button>
            <button className={ctrl === "manual" ? "seg-on" : ""} onClick={() => setCtrlMode("manual")}
              title="PC 直接下发目标位置">
              手动模式
            </button>
          </div>
          {/* 两个视图叠放同一网格单元：卡高恒等于较高者，自动/手动切换不跳动 */}
          <div style={{ display: "grid" }}>
            <div style={{ gridArea: "1 / 1", visibility: ctrl === "auto" ? "visible" : "hidden" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {MODES.map((m, i) => (
                  <button key={m}
                    className={mode === i ? "seg-on" : ""}
                    disabled={busy !== ""}
                    onClick={() => c.setModeIdx(i)}>
                    {m}
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center", flexWrap: "wrap", rowGap: 6 }}>
                <button disabled={busy !== ""}
                  title="开始指令：基地立即开始移动（0x3205 BDOOR）"
                  onClick={() => c.setDoor(true)}>
                  开始指令
                </button>
                <button disabled={busy !== ""}
                  title="停止指令：立即停在原地；不发开始指令不再运动（0x3205 BDOOR）"
                  onClick={() => c.setDoor(false)}>
                  停止指令
                </button>
                <button className={c.fired ? "seg-on" : ""} disabled={busy !== "" || !c.started}
                  onClick={c.fireTrigger}
                  title={c.started
                    ? "发射触发（0x3206 BTRIG）：基地开始执行档位程序；发射联动时该指令由镖架经主机自动发来"
                    : c.running
                      ? "停止状态：发射指令无效，请先按「开始指令」"
                      : "基地未使能：请先在右侧点「使能」（失能下不自动使能）"}>
                  发射指令
                </button>
                <span className={c.started ? "dir-in" : "muted"} style={{ marginLeft: "auto", fontSize: 12 }}>
                  {c.started ? "● 开启状态" : "○ 停止状态"} · 当前档位：{mode != null ? MODES[mode] : "读取中…"}
                </span>
              </div>
            </div>
            <div style={{ gridArea: "1 / 1", visibility: ctrl === "manual" ? "visible" : "hidden" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input type="number" style={{ width: 100 }} value={target}
                  min={-STROKE} max={STROKE}
                  onChange={(e) => setTarget(Math.max(-STROKE, Math.min(STROKE, Number(e.target.value) || 0)))} />
                <span className="muted">mm</span>
                <button disabled={busy !== "" || !running} onClick={() => c.startMove(target, speedSel)}
                  title={running ? "下发目标并开始移动" : "基地未使能：请先在右侧点「使能」"}>
                  开始移动
                </button>
              </div>
              <input type="range" style={{ width: "100%", marginTop: 10 }} min={-STROKE} max={STROKE} step={5}
                value={target} onChange={(e) => setTarget(Number(e.target.value))} />
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
                <span className="muted" style={{ fontSize: 12 }}>运动速度：</span>
                {(["平移速度", "停止速度"] as const).map((n, i) => (
                  <button key={n} className={speedSel === i ? "seg-on" : ""} disabled={busy !== ""}
                    style={{ padding: "3px 12px", fontSize: 12 }}
                    onClick={() => setSpeedSel(i as 0 | 1)}>
                    {n}
                  </button>
                ))}
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                手动模式：使能后设定目标、选速度，点「开始移动」前往；切换目标会自动停在原地，再点「开始移动」前往新目标。失能后须重新使能。
              </div>
            </div>
          </div>
          <div style={{ borderTop: "1px solid var(--line)", paddingTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
              <input type="checkbox" checked={autolink} disabled={busy !== ""}
                onChange={(e) => {
                  const v = e.target.checked;
                  setAutolink(v);
                  act("联动设置", () => postJSON("/api/base/autolink", { enabled: v }))
                    .then((ok) => !ok && setAutolink(!v));
                }} />
              <b>发射联动</b>
            </label>
            <span className="muted" style={{ fontSize: 12 }}>
              镖架发射成功 → 自动发「发射指令」；急停 → 装甲板立即停止运动（保持使能，失能仅用于意外保护）
            </span>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <b>参数设置</b>
            <span className="muted">写入=会话生效，保存=写入 flash</span>
            <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              <button disabled={busy !== ""} onClick={loadParams}
                title="把 flash 已存值恢复为当前值，放弃未保存的会话修改（不恢复出厂）">
                从 Flash 读取
              </button>
              <button disabled={busy !== ""} onClick={saveParams}>
                全部保存到 Flash
              </button>
            </div>
          </div>
          {params == null ? (
            <div className="muted">目录读取中…</div>
          ) : (
            <table className="tele">
              <tbody>
                {params.map((p) => {
                  const key = p.name.trim();
                  const edit = paramEdits[p.id] ?? "";
                  const val = edit === "" ? p.current : Number(edit);
                  const out = edit !== "" && (val < p.min || val > p.max || Number.isNaN(val));
                  return (
                    <tr key={p.id}>
                      <td style={{ width: 90 }}>
                        {PARAM_NAMES[key] ?? key}
                        {p.modified && <span className="dir-out" title="会话值与已存值不同"> ●</span>}
                      </td>
                      <td style={{ width: 110 }}>
                        <input type="number" style={{ width: 100 }} value={edit === "" ? p.current : edit}
                          min={p.min} max={p.max}
                          onChange={(e) => setParamEdits((m) => ({ ...m, [p.id]: e.target.value }))} />
                      </td>
                      <td className="muted" style={{ width: 60 }}>{p.unit.trim()}</td>
                      <td className="muted param-range" style={{ fontSize: 12 }}>
                        范围 {p.min}~{p.max} · 已存 {p.saved}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button disabled={busy !== "" || out || val === p.current}
                          onClick={() => writeParam(p)}>
                          写入
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}
