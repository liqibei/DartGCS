export interface TelemetryPoint {
  var: number;
  name: string;
  value: number;
  ts: number;
}

export interface Device {
  id: number;
  kind: "launcher" | "base" | "dart" | "unknown";
  name: string;
  online: boolean;
  battery_mv: number;
  loss_rate: number;
  link_name: string;
  first_seen: number;
  reboot_count: number;
  last_seen: number;
  telemetry: TelemetryPoint[];
}

export interface FrameLogEntry {
  ts: number;
  dir: "in" | "out";
  link: string;
  src: string;
  type: string;
  plane: string;
  len: number;
  hex: string;
}

export interface Session {
  id: string;
  created_at: string;
  dart_addr: number;
  params: Record<string, unknown>;
  notes: string;
  refs: { video: string | null; csv: string | null };
}
