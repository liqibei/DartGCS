import type { Device } from "../types";
import { Sparkline } from "./Sparkline";

const KIND_LABEL: Record<Device["kind"], string> = {
  launcher: "发射架",
  base: "基地",
  dart: "飞镖",
  unknown: "未知",
};

export default function DeviceCard({
  device,
  history,
}: {
  device: Device;
  history: Map<string, number[]>;
}) {
  return (
    <div className="card">
      <div className="card-head">
        <span className={`dot ${device.online ? "on" : "off"}`} />
        <b>{device.name}</b>
        <span className="tag">{KIND_LABEL[device.kind]}</span>
      </div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
        链路 {device.link_name} · 电池{" "}
        {device.online && device.battery_mv ? (device.battery_mv / 1000).toFixed(2) : "--"} V ·
        质量 {device.link_quality}
      </div>
      {device.telemetry.length === 0 ? (
        <div className="muted">无遥测变量</div>
      ) : (
        <table className="tele">
          <tbody>
            {device.telemetry.map((p) => (
              <tr key={p.var}>
                <td className="muted">{p.name}</td>
                <td>{p.value.toFixed(2)}</td>
                <td style={{ textAlign: "right" }}>
                  <Sparkline values={history.get(`${device.addr}:${p.var}`) ?? []} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
