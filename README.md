# NetSim v2.0 — Protocol-Accurate TCP/IP Network Simulator

6th Semester Computer Networks — course project  
**Stack:** **Next.js 14** + **TypeScript** (frontend) · **Python FastAPI** (backend) · **WebSockets**

Formal submission specification: **[SPEC.md](SPEC.md)**.

---

## Current implementation (summary)

### Live vs stub layers (TCP/IP model on screen)

| TCP/IP layer | Status | Notes |
|----------------|--------|--------|
| **Physical** | Live | Line encodings, signal generation, `BITS_SENT` / `SIGNAL_DRAWN` events |
| **Data Link** | Live | Framing, error control, MAC/access, ARQ flow control; topology mode with switches/hubs |
| **Network / Transport / Application** | Stub | Event types and UI placeholders; not full protocol stacks |

Session + Presentation (OSI 5–6) are folded into **Application** in the UI, matching a **4-layer TCP/IP** teaching model.

### Backend capabilities

- **REST:** `GET /health`, `GET /api/encodings`, `GET /api/media`, `GET /api/datalink/options`
- **Simulation:** `POST /api/simulate/physical` (bit string), `POST /api/simulate/datalink` (message + DLL options)
- **Topology mode:** When `topology_devices` + `topology_links` are sent with a datalink request, **`simulate_datalink_topology`** runs: host routing, **switch learning** (MAC → port), **unknown unicast flood**, hub flood, **persistent switch tables** per session, **broadcast/collision domain** counts, learning summary for the UI
- **WebSocket:** `GET ws://…/ws/{session_id}` — broadcasts `SimEvent` JSON when clients are connected during a run

### Data link (educational)

- **Framing:** fixed-size; variable (HDLC-style flag + byte stuffing)
- **Error control:** CRC-32, checksum, none; optional inject-error for demos
- **MAC:** Pure/slotted ALOHA, CSMA, CSMA/CD, CSMA/CA (stepwise logs, not full PHY timing)
- **Flow / ARQ:** stop-and-wait, Go-Back-N, selective repeat

### Design patterns (backend)

| Pattern | Where |
|--------|--------|
| **Strategy** | Encoding, medium, framing, error control, MAC, flow |
| **Template method** | Layer classes |
| **Observer** | Layer → `SimEvent` → WebSocket |
| **Factory** | Physical / data link / device factories |

---

## Running locally

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000** (landing) or **http://localhost:3000/simulator** (simulator).

### Environment (optional)

| Variable | Default |
|----------|---------|
| `NEXT_PUBLIC_BACKEND_URL` | `http://localhost:8000` |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000` |

### Tests

```bash
# Backend
cd backend && pytest

# Frontend (Vitest)
cd frontend && npm test
```

---

## UI features (current)

- **Topology canvas** — drag device type from palette or click-to-place; wired (solid) vs wireless (dashed) links
- **Presets** — demo / star / bus / mesh; clear canvas
- **Modes** — PHY-only vs PHY + DLL; **DLL config** panel (toggle); **Advanced** (clock Hz, samples/bit, quick lab presets)
- **Resizable panels** — sidebar width, waveform panel height
- **Waveform** — **Canvas 2D** plot of encoded signal (from `encodeSignal` / PHY events)
- **Event log** — layer filters, collapsible section
- **Switch MAC tables** — per-switch port/MAC view; scrollable list when many switches; reset learning + topology fingerprint behavior from backend
- **Overlays** — device tooltip and context menus stack above top bars so properties are not hidden behind encoding/config UI
- **Status** — API / WebSocket connectivity indicators in the top bar

---

## WebSocket / event contract

Backend emits **`SimEvent`** JSON for layer actions. Types include `FRAMING_INFO`, `ERROR_DETECTED`, `ACCESS_CONTROL`, `FLOW_CONTROL`, `SESSION_INFO`, and standard frame/PHY events. The frontend stores and displays them in the event log and pipeline view.

---

## Troubleshooting

- **`fetch failed` / `ENOTFOUND registry.npmjs.org` on `npm run dev`:** Next.js may try to reach the npm registry during dev startup. If DNS/network fails, you may see a stack trace; the server often still reports **Ready**. Fix network/DNS or ignore if the app loads at localhost.
