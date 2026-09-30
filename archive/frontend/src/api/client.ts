export type WsMessage = { type: string; data?: unknown };

export async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`GET ${url} -> ${r.status}`);
  return r.json() as Promise<T>;
}

export async function postJSON<T>(
  url: string,
  body: unknown,
  method: "POST" | "PATCH" = "POST"
): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${method} ${url} -> ${r.status}`);
  return r.json() as Promise<T>;
}

/** 自动重连的 WebSocket 客户端；消息统一回调。 */
export class WsClient {
  onMessage?: (msg: WsMessage) => void;
  onStatus?: (up: boolean) => void;
  private ws: WebSocket | null = null;
  private closed = false;
  private timer: number | undefined;

  start(): void {
    this.connect();
  }

  stop(): void {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
  }

  private connect(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => this.onStatus?.(true);
    ws.onclose = () => {
      this.onStatus?.(false);
      if (!this.closed) this.timer = window.setTimeout(() => this.connect(), 1500);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => {
      try {
        this.onMessage?.(JSON.parse(e.data));
      } catch {
        // 非 JSON 消息忽略
      }
    };
  }
}
