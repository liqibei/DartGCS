import { createContext, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { ReactNode } from "react";
import { WsClient, type WsMessage } from "../api/client";
import type { Device } from "../types";

interface DeviceState {
  devices: Device[];
  wsUp: boolean;
}

interface HistoryState {
  /** 遥测历史：key = `${addr}:${var}`，最多保留 120 点 */
  map: Map<string, number[]>;
}

// 设备表与遥测历史分两个 Context：遥测 10Hz 到达只触发图表类组件重渲染，
// 导航/表单等静态结构只订阅 DeviceContext，不受高频更新影响。
const DeviceContext = createContext<DeviceState>({ devices: [], wsUp: false });
const HistoryContext = createContext<HistoryState>({ map: new Map() });

export function LiveProvider({ children }: { children: ReactNode }) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [wsUp, setWsUp] = useState(false);
  const mapRef = useRef(new Map<string, number[]>());
  const [rev, bump] = useReducer((x: number) => x + 1, 0);

  useEffect(() => {
    const client = new WsClient();
    client.onStatus = setWsUp;
    client.onMessage = (msg: WsMessage) => {
      if (msg.type === "hello" || msg.type === "devices") {
        setDevices(msg.data as Device[]);
      } else if (msg.type === "telemetry") {
        const data = msg.data as { addr: number; var: number; value: number }[];
        for (const p of data) {
          const key = `${p.addr}:${p.var}`;
          const arr = mapRef.current.get(key) ?? [];
          arr.push(p.value);
          if (arr.length > 120) arr.shift();
          mapRef.current.set(key, arr);
        }
        bump();
      }
    };
    client.start();
    return () => client.stop();
  }, []);

  const deviceValue = useMemo(() => ({ devices, wsUp }), [devices, wsUp]);
  const historyValue = useMemo(() => ({ map: mapRef.current }), [rev]);

  return (
    <DeviceContext.Provider value={deviceValue}>
      <HistoryContext.Provider value={historyValue}>{children}</HistoryContext.Provider>
    </DeviceContext.Provider>
  );
}

export function useDevices(): DeviceState {
  return useContext(DeviceContext);
}

export function useHistory(): HistoryState {
  return useContext(HistoryContext);
}
