import { useEffect, useState } from "react";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { getJSON } from "./api/client";
import { LiveProvider, useDevices } from "./live/LiveContext";
import Base from "./pages/Base";
import Diagnostics from "./pages/Diagnostics";
import Darts from "./pages/Darts";
import Launcher from "./pages/Launcher";
import Overview from "./pages/Overview";
import Replay from "./pages/Replay";

function HealthDot() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    const check = () =>
      getJSON("/api/health")
        .then(() => setOk(true))
        .catch(() => setOk(false));
    check();
    const t = setInterval(check, 2000);
    return () => clearInterval(t);
  }, []);
  return <span className={`dot ${ok ? "on" : "off"}`} title="后端 /api/health" />;
}

interface HotspotState {
  available: boolean;
  active: boolean;
  ssid: string;
  url: string;
  hint: string;
  lan_urls: string[];
  lan_hint: string;
}

const HOTSPOT_BLANK: HotspotState = {
  available: false, active: false, ssid: "", url: "", hint: "", lan_urls: [], lan_hint: "",
};

/** 手机控制卡：同一局域网直访（首选）+ 一键热点（现场无网络时的备用）。 */
function HotspotCard() {
  const [st, setSt] = useState<HotspotState>(HOTSPOT_BLANK);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");

  const refresh = () =>
    getJSON<HotspotState>("/api/hotspot").then(setSt).catch(() => setSt(HOTSPOT_BLANK));

  useEffect(() => {
    refresh();
  }, []);

  const toggle = async () => {
    setBusy(true);
    try {
      const r = await fetch("/api/hotspot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on: !st.active }),
      });
      setSt((await r.json()) as HotspotState);
    } catch {
      // 后端不可达时静默
    } finally {
      setBusy(false);
    }
  };

  const copy = (u: string) => {
    navigator.clipboard?.writeText(u).then(() => {
      setCopied(u);
      window.setTimeout(() => setCopied(""), 1500);
    }).catch(() => {});
  };

  return (
    <div className="hotspot-card">
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <b>手机控制</b>
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
        手机连到与电脑相同的网络（手机热点 / 路由器 / 现场 AP）后访问：
      </div>
      {st.lan_urls.length > 0 ? (
        st.lan_urls.map((u) => (
          <div key={u} style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 4 }}>
            <a href={u} style={{ fontSize: 12, wordBreak: "break-all" }}
              onClick={(e) => e.preventDefault()}>
              {u}
            </a>
            <button style={{ padding: "0 6px", fontSize: 11, flexShrink: 0 }}
              onClick={() => copy(u)}>
              {copied === u ? "已复制" : "复制"}
            </button>
          </div>
        ))
      ) : (
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
          {st.lan_hint || "未检测到局域网地址"}
        </div>
      )}
      <div style={{ borderTop: "1px solid var(--line)", margin: "8px 0 6px" }} />
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span className="muted" style={{ fontSize: 12 }}>备用：电脑开热点</span>
        <button className={st.active ? "seg-on" : ""} disabled={busy || !st.available}
          style={{ marginLeft: "auto", padding: "2px 10px", fontSize: 12 }}
          onClick={toggle}
          title={st.hint}>
          {st.available ? (busy ? "切换中…" : st.active ? "关闭热点" : "开启热点") : "不可用"}
        </button>
      </div>
      {st.active && (
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
          热点 {st.ssid}（密码 dart2027）→ {st.url}
        </div>
      )}
      {!st.active && st.hint && (
        <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{st.hint}</div>
      )}
    </div>
  );
}

function Shell() {
  const { wsUp } = useDevices();
  return (
    <div className="app">
      <aside>
        <div className="logo">Dart GCS</div>
        <nav>
          <NavLink to="/" end>
            设备总览
          </NavLink>
          <NavLink to="/launcher">发射架</NavLink>
          <NavLink to="/base">基地</NavLink>
          <NavLink to="/darts">飞镖</NavLink>
          <NavLink to="/replay">回放分析</NavLink>
          <NavLink to="/diagnostics">协议调试</NavLink>
        </nav>
        <div className="side-note muted">
          <HotspotCard />
          <div style={{ marginTop: 8 }}>后端 <span className={`dot ${wsUp ? "on" : "off"}`} /></div>
        </div>
      </aside>
      <main>
        <header>
          <b>飞镖调参上位机</b>
          <span className="muted">RMUC 2027 · Dart System</span>
          <span className="muted" style={{ marginLeft: "auto" }}>
            后端 <HealthDot />
          </span>
        </header>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/launcher" element={<Launcher />} />
          <Route path="/base" element={<Base />} />
          <Route path="/darts" element={<Darts />} />
          <Route path="/replay" element={<Replay />} />
          <Route path="/diagnostics" element={<Diagnostics />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <LiveProvider>
      <HashRouter>
        <Shell />
      </HashRouter>
    </LiveProvider>
  );
}
