import DeviceCard from "../components/DeviceCard";
import { useDevices, useHistory } from "../live/LiveContext";

export default function Overview() {
  const { devices } = useDevices();
  const { map: history } = useHistory();
  const online = devices.filter((d) => d.online).length;
  return (
    <div className="page">
      <h2>设备总览</h2>
      <p className="muted">
        在线 {online}/{devices.length}。当前数据来自 Mock 仿真链路（无硬件演示用），真实设备经
        UDP/TCP/串口接入后自动替换。
      </p>
      <div className="grid">
        {devices.map((d) => (
          <DeviceCard key={d.addr} device={d} history={history} />
        ))}
      </div>
    </div>
  );
}
