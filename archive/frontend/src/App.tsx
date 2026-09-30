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
          <div>后端 <span className={`dot ${wsUp ? "on" : "off"}`} /></div>
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
