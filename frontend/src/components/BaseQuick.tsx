import { useEffect, useState } from "react";
import { getJSON, postJSON } from "../api/client";
import { useDevices, useHistory } from "../live/LiveContext";
import type { Device } from "../types";

/** 基地控制共享层：设备总览卡片与基地子页共用同一套控制逻辑（乐观更新 + 遥测确认）。
 *  总览卡片只放基本控制并跟随子页的 自动/手动 选择（useCtrlMode 跨页共享）；详细设置进子页。 */
export const BASE_ID = 0x20;
export const STROKE = 280; // 行程 ±280 mm，与固件参数 home/range 量程一致

export const MODES = ["固定", "随机固定", "随机移动", "末端移动"];

// 固件参数键名 → 中文显示名（协议不含中文，走 PC 端映射；目录条目名按协议 8B 截断）
export const PARAM_NAMES: Record<string, string> = {
  speed: "平移速度",
  estop_sp: "停止速度",
  estop_speed: "停止速度",
  move_int: "运动间隔",
  move_interval: "运动间隔",
  launch_d: "发射延迟",
  launch_delay: "发射延迟",
  range: "行程半径",
};

export interface ParamInfo {
  id: number;
  name: string;
  type: number;
  unit: string;
  min: number;
  max: number;
  default: number;
  saved: number;
  current: number;
  modified: boolean;
}

// BSTATE 解出的遥测变量（devices/manager.py：0x71~0x75=113~117），WS 键用十进制 ID
export const V = {
  cur: `${BASE_ID}:113`, tgt: `${BASE_ID}:114`,
  run: `${BASE_ID}:115`, light: `${BASE_ID}:116`, door: `${BASE_ID}:117`, started: `${BASE_ID}:118`,
};

export function last(arr: number[] | undefined): number | undefined {
  return arr && arr.length ? arr[arr.length - 1] : undefined;
}

export function latest(device: Device | undefined, name: string): number | undefined {
  return device?.telemetry.find((p) => p.name === name)?.value;
}

// ---- 自动/手动 选择：跨页共享（总览卡片与子页始终一致） --------------------
export type CtrlMode = "auto" | "manual";
let ctrlState: CtrlMode =
  (localStorage.getItem("baseCtrl") as CtrlMode | null) ?? "auto";
const ctrlListeners = new Set<(m: CtrlMode) => void>();

export function useCtrlMode(): [CtrlMode, (m: CtrlMode) => void] {
  const [ctrl, setCtrl] = useState<CtrlMode>(ctrlState);
  useEffect(() => {
    ctrlListeners.add(setCtrl);
    return () => {
      ctrlListeners.delete(setCtrl);
    };
  }, []);
  const setCtrlMode = (m: CtrlMode) => {
    ctrlState = m;
    localStorage.setItem("baseCtrl", m);
    ctrlListeners.forEach((fn) => fn(m));
  };
  return [ctrl, setCtrlMode];
}

export function useBaseControl() {
  const { devices } = useDevices();
  const { map: history } = useHistory();
  const base = devices.find((d) => d.id === BASE_ID);
  const [ctrl, setCtrlMode] = useCtrlMode();

  const [runOpt, setRunOpt] = useState<boolean | null>(null); // 乐观覆盖：点击即生效
  const [lightOpt, setLightOpt] = useState<boolean | null>(null);
  const [doorOpt, setDoorOpt] = useState<boolean | null>(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [mode, setMode] = useState<number | null>(null);

  useEffect(() => {
    getJSON<{ mode: number }>("/api/base/state").then((r) => setMode(r.mode)).catch(() => {});
  }, []);

  const tRun = (last(history.get(V.run)) ?? latest(base, "running") ?? 0) > 0.5;
  const tLight = (last(history.get(V.light)) ?? latest(base, "light") ?? 0) > 0.5;
  const tDoor = (last(history.get(V.door)) ?? latest(base, "door") ?? 0) > 0.5;
  const tStarted = (last(history.get(V.started)) ?? latest(base, "started") ?? 0) > 0.5;
  const running = runOpt ?? tRun;
  const light = lightOpt ?? tLight;
  const door = doorOpt ?? tDoor;
  const started = tStarted; // 开启状态：仅开始指令置位；停止状态下发射指令无效

  // 遥测追上乐观值后撤掉覆盖，之后以设备上报为准
  useEffect(() => {
    if (runOpt !== null && tRun === runOpt) setRunOpt(null);
  }, [tRun, runOpt]);
  useEffect(() => {
    if (lightOpt !== null && tLight === lightOpt) setLightOpt(null);
  }, [tLight, lightOpt]);
  useEffect(() => {
    if (doorOpt !== null && tDoor === doorOpt) setDoorOpt(null);
  }, [tDoor, doorOpt]);

  const cur = last(history.get(V.cur)) ?? latest(base, "cur_pos_mm");
  const tgt = last(history.get(V.tgt)) ?? latest(base, "tgt_pos_mm");

  const act = async (label: string, fn: () => Promise<unknown>): Promise<boolean> => {
    setBusy(label);
    setMsg(`${label}…`);
    try {
      await fn();
      setMsg(`${label}完成`);
      return true;
    } catch (e) {
      setMsg(`${label}失败：${e}`);
      return false;
    } finally {
      setBusy("");
    }
  };

  const setRun = (v: boolean) => {
    setRunOpt(v); // 先亮再说，失败回退
    act(v ? "使能" : "失能", () => postJSON("/api/base/run", { run: v ? 1 : 0 }))
      .then((ok) => !ok && setRunOpt(null));
  };
  const setLight = (v: boolean) => {
    setLightOpt(v);
    act(v ? "开灯" : "关灯", () => postJSON("/api/base/light", { on: v }))
      .then((ok) => !ok && setLightOpt(null));
  };
  // 舱门即指令通道：开启指令=开，停止指令=关（不叫"关闭舱门"）
  const setDoor = (v: boolean) => {
    setDoorOpt(v);
    act(v ? "开始指令" : "停止指令", () => postJSON("/api/base/door", { on: v }))
      .then((ok) => !ok && setDoorOpt(null));
  };
  // 发射指令：手动模拟镖架经主机发来的发射触发（0x3206），联动打开时发射会自动触发。
  // 失能下设备拒绝（不隐式使能），须先点使能。
  const [fired, setFired] = useState(false);
  const fireTrigger = () => {
    act("发射指令", () => postJSON("/api/base/trigger", {})).then((ok) => {
      if (!ok) return;
      setFired(true);
      window.setTimeout(() => setFired(false), 1000);
    });
  };

  const setModeIdx = (i: number) => {
    const prev = mode;
    setMode(i);
    act(`切换 ${MODES[i]}`, () => postJSON("/api/base/mode", { mode: i }))
      .then((ok) => !ok && prev != null && setMode(prev));
  };
  // 手动模式「开始移动」：下发目标（切换即停）+ 开始指令前往
  const startMove = (target: number, sel: number) =>
    act("开始移动", async () => {
      await postJSON("/api/base/target", { pos: target, sel });
      await postJSON("/api/base/door", { on: true });
    });

  return {
    base, history, ctrl, setCtrlMode,
    running, light, door, started, cur, tgt, mode, busy, msg, setMsg, act, fired,
    setRun, setLight, setDoor, fireTrigger, setModeIdx, startMove,
  };
}

const miniBtn = { padding: "2px 9px", fontSize: 12 } as const;

/** 基地轨道可视化：全长 700mm = 行程 560（±280）+ 板宽 140。
 *  装甲板永远蓝色，两侧灯条蓝色，板中间金色 ROBOMASTER 字样（大轨道显示）。绿线为目标位置。 */
export function BaseTrack({ cur, tgt, big = false }: {
  cur?: number; tgt?: number; big?: boolean;
}) {
  const mm = (v: number) => `${((Math.max(-350, Math.min(350, v)) + 350) / 700) * 100}%`;
  return (
    <div className={big ? "track track-big" : "track"}>
      {tgt != null && (
        <div className="track-marker" style={{ left: mm(tgt) }} title={`目标 ${tgt.toFixed(0)} mm`} />
      )}
      {cur != null && (
        <div className="track-plate" style={{ left: mm(cur) }}
          title={`装甲板当前位置 ${cur.toFixed(0)} mm（板宽 140mm）`}>
          <div className="plate-strip" />
          <div className="plate-body">{big && <span className="plate-text">ROBOMASTER</span>}</div>
          <div className="plate-strip" />
        </div>
      )}
    </div>
  );
}

/** 设备总览基地卡片：位置条 + 当前档位 + 跟随子页 自动/手动 的控制组（无遥测图表）。
 *  灯/使能失能固定右上角；使能按键红绿着色（绿=未使能可点使能，红=已使能点失能）。 */
export function BaseQuick() {
  const c = useBaseControl();
  const [target, setTarget] = useState(0);
  const [speedSel, setSpeedSel] = useState<0 | 1>(0);

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span className="tag">模式：{c.mode != null ? MODES[c.mode] : "读取中"}</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button style={miniBtn} className={c.light ? "seg-on" : ""} disabled={c.busy !== ""}
            onClick={() => c.setLight(!c.light)}>
            {c.light ? "💡 关" : "💡 开"}
          </button>
          {c.running
            ? <button style={miniBtn} className="btn-green" disabled={c.busy !== ""}
                onClick={() => c.setRun(false)}>■ 失能</button>
            : <button style={miniBtn} className="btn-red" disabled={c.busy !== ""}
                onClick={() => c.setRun(true)}>▶ 使能</button>}
        </span>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", marginTop: 6 }}>
        <span className="muted" style={{ fontSize: 12 }}>
          {c.cur != null ? `当前 ${c.cur.toFixed(0)} mm` : "当前 --"} · {c.tgt != null ? `目标 ${c.tgt.toFixed(0)} mm` : "目标 --"} · {c.running ? "已使能" : "未使能"} · {c.started ? "开启状态" : "停止状态"}
        </span>
        <a href="#/base" className="muted" style={{ fontSize: 12, marginLeft: "auto" }}>
          详细设置 →
        </a>
      </div>

      <div style={{ marginTop: 10 }}>
        <BaseTrack cur={c.cur} tgt={c.tgt} />
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "center" }}>
        {c.ctrl === "auto" ? (
          <>
            <button style={miniBtn} disabled={c.busy !== ""}
              title="开始指令：基地立即开始移动（0x3205）"
              onClick={() => c.setDoor(true)}>
              开始指令
            </button>
            <button style={miniBtn} disabled={c.busy !== ""}
              title="停止指令：立即停在原地；不发开始指令不再运动（0x3205）"
              onClick={() => c.setDoor(false)}>
              停止指令
            </button>
            <button style={miniBtn} className={c.fired ? "seg-on" : ""}
              disabled={c.busy !== "" || !c.started}
              title={c.started ? "发射触发（0x3206）" : c.running ? "停止状态：发射指令无效，请先按「开始指令」" : "基地未使能：请先点「使能」"}
              onClick={c.fireTrigger}>
              {c.fired ? "已下发 ✓" : "发射指令"}
            </button>
          </>
        ) : (
          <>
            <input type="number" style={{ width: 72, padding: "3px 6px", fontSize: 12 }}
              value={target} min={-STROKE} max={STROKE}
              onChange={(e) => setTarget(Math.max(-STROKE, Math.min(STROKE, Number(e.target.value) || 0)))} />
            <span className="muted" style={{ fontSize: 12 }}>mm</span>
            <button style={miniBtn} disabled={c.busy !== "" || !c.running}
              title={c.running ? "下发目标并开始移动" : "基地未使能：请先点「使能」"}
              onClick={() => c.startMove(target, speedSel)}>
              开始移动
            </button>
            {(["平移", "停止"] as const).map((n, i) => (
              <button key={n} style={{ ...miniBtn, padding: "2px 7px" }}
                className={speedSel === i ? "seg-on" : ""} disabled={c.busy !== ""}
                onClick={() => setSpeedSel(i as 0 | 1)}>
                {n}
              </button>
            ))}
          </>
        )}
      </div>
      {c.ctrl === "manual" && (
        <input type="range" style={{ width: "100%", marginTop: 8 }} min={-STROKE} max={STROKE} step={5}
          value={target} onChange={(e) => setTarget(Number(e.target.value))} />
      )}
      {c.msg && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{c.msg}</div>}
    </div>
  );
}
