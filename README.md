# NetSim v2.0 — Protocol-Accurate TCP/IP Network Simulator

6th Semester Computer Networks Course Project  
Stack: **Next.js 14 + TypeScript** (frontend) · **Python FastAPI** (backend) · **WebSockets**

---

## What's implemented (Phase 1 + 2)

### TCP/IP Layer Model
Session + Presentation (OSI 5/6) are merged into the Application layer — matching the TCP/IP 4-layer model.

| TCP/IP Layer | OSI Equiv | Status | Protocols |
|---|---|---|---|
| Physical | 1 | ✅ LIVE | NRZ-L, NRZ-I, Manchester, Diff.Manchester, AMI, 4B5B |
| Data Link | 2 | ✅ LIVE | Framing, Error Control, MAC, Flow Control |
| Network | 3 | Stub | IP, Routing, TTL |
| Transport | 4 | Stub | TCP state machine, UDP |
| Application | 5/6/7 | Stub | HTTP, DNS, ICMP |

### Data Link Sub-layers
**Framing**
- Fixed-size (N-byte pad/truncate)
- Variable-size, bit-oriented (HDLC: 0x7E flag delimiter + byte stuffing)

**Error Control** (Strategy pattern)
- `ChecksumErrorControl` — RFC-1071 Internet 16-bit checksum
- `CRCErrorControl`      — IEEE 802.3 CRC-32 (zlib)

**Access Control / MAC** (Strategy pattern)
- `PureAloha`    — transmit immediately, random back-off on collision
- `SlottedAloha` — wait for slot boundary
- `CSMA`         — 1-persistent carrier sense
- `CSMACD`       — CSMA + collision detect, binary exponential back-off (Ethernet)
- `CSMACA`       — CSMA + collision avoid, DIFS/SIFS/CW, optional RTS/CTS (802.11)

**Flow Control / ARQ** (Strategy pattern)
- `StopAndWaitARQ`    — window=1, ACK each frame
- `GoBackNARQ`        — configurable window, retransmit from error
- `SelectiveRepeatARQ`— configurable window, retransmit only errored frame

All MAC and ARQ protocols return full step-by-step educational logs streamed to the UI.

---

## Design Patterns Used
| Pattern | Where |
|---|---|
| **Strategy** | IEncodingStrategy, ITransmissionMedium, IFraming, IErrorControl, IMACProtocol, IFlowControl, IAppProtocol |
| **Template Method** | PhysicalLayer, DataLinkLayer, NetworkLayer, TransportLayer, ApplicationLayer |
| **Observer** | ILayerObserver → WebSocketEmitter broadcasts SimEvents |
| **Factory Method** | PhysicalLayerFactory, DataLinkLayerFactory, DeviceFactory |
| **Value Object** | Bits, Signal, EthernetFrame, IPPacket, ARPPacket |
| **State Machine** | TCPStateMachine (CLOSED→SYN_SENT→ESTABLISHED→…) |

---

## Running

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
npm run dev   # → http://localhost:3000/simulator
```

---

## UI Features
- **Topology canvas** — drag devices from palette, place anywhere
- **Wired vs Wireless** — solid blue lines (wired) vs dashed orange lines (wireless), visual distinction in both links and labels
- **Resizable panels** — sidebar (drag left edge ↔), waveform panel (drag top ↕)
- **PHY / PHY+DLL mode toggle** — switch between physical-only and full data link simulation
- **DLL Config panel** — toggle with ⚙ button; configure all 4 sublayers independently
- **Layer flash** — TCP/IP stack sidebar highlights the active layer in real time
- **Event log** — per-layer filter (PHY/DLL/NET/TRA/APP/ENG), scrollable, 200 entries
- **Waveform** — live D3-rendered signal with glow, resizable height
- **Right-click menu** — connect (choose wired/wireless), set src/dst, delete
- **Error injection** — toggle "Inject Error" in DLL Config to demo CRC/Checksum detection

---

## WebSocket Contract (unchanged)
Backend emits `SimEvent` JSON on every layer action.  
New event types added in v2: `FRAMING_INFO`, `ERROR_DETECTED`, `ACCESS_CONTROL`, `FLOW_CONTROL`, `ACK_SENT`, `SESSION_INFO`, `APP_ENCODING`.  
Frontend handles all types via the event log and layer highlight system.
