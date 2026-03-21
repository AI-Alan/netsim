import { create } from "zustand";
import type { SimEvent, SignalData, DeviceNode, NetworkLink } from "./types";

interface SimStore {
  sessionId:    string;
  wsConnected:  boolean;
  events:       SimEvent[];
  latestSignal: SignalData | null;
  simRunning:   boolean;
  setSession:    (id: string) => void;
  setConnected:  (v: boolean) => void;
  addEvent:      (e: SimEvent) => void;
  clearEvents:   () => void;
  setSimRunning: (v: boolean) => void;
}

export const useSimStore = create<SimStore>((set) => ({
  sessionId:    "",
  wsConnected:  false,
  events:       [],
  latestSignal: null,
  simRunning:   false,
  setSession:    (id)  => set({ sessionId: id }),
  setConnected:  (v)   => set({ wsConnected: v }),
  addEvent:      (e)   => set((s) => ({
    events:       [e, ...s.events].slice(0, 200),
    latestSignal: e.signal ?? s.latestSignal,
  })),
  clearEvents:   ()    => set({ events: [], latestSignal: null }),
  setSimRunning: (v)   => set({ simRunning: v }),
}));
