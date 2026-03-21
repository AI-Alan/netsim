import { useSimStore } from "./store";
import type { SimEvent } from "./types";

let ws: WebSocket | null = null;

export function connectWS(sessionId: string, backendUrl = "ws://localhost:8000"): void {
  if (ws) { ws.close(); ws = null; }
  try {
    ws = new WebSocket(`${backendUrl}/ws/${sessionId}`);
    ws.onopen  = () => useSimStore.getState().setConnected(true);
    ws.onclose = () => useSimStore.getState().setConnected(false);
    ws.onerror = () => useSimStore.getState().setConnected(false);
    ws.onmessage = (msg) => {
      try {
        const event: SimEvent = JSON.parse(msg.data);
        useSimStore.getState().addEvent(event);
      } catch (_) {}
    };
  } catch (_) {}
}

export function disconnectWS(): void { ws?.close(); ws = null; }
