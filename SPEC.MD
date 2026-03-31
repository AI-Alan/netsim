# ITL351 — NetSim: Specification Document

**Course:** ITL351 — Computer Networks Lab
**Assignment:** Semester Project — Submission 1
**Submission deadline:** March 25, 2026 (via Gradescope)
**Project title:** Network Simulator implementing the Protocol Stack

**Implementation:** NetSim v2.0
**Repository:** https://github.com/AI-Alan/netsim
**Stack:** Next.js 14 + TypeScript (frontend) · Python FastAPI (backend) · WebSockets (real-time events)

**Group Members:**

| Name | Enrollment No. |
|------|----------------|
| Aman Kumar Yadav | 2023BITE045 |
| Ashish Chaudhary | 2023BITE061 |
| Akshat Singh | 2023BITE029 |


---

## 1. Assignment Alignment (Submission 1)

NetSim implements all minimum deliverables for Submission 1 across both the Physical and Data Link layers.

For the **Physical layer**, the simulator supports creating end devices (hosts) and hubs, connecting them into arbitrary topologies via wired or wireless links, and simulating data transmission between any two nodes. Hub flooding behavior is faithfully reproduced — frames are forwarded to all ports except the ingress.

For the **Data Link layer**, the simulator supports Layer 2 switches with MAC address learning and forwarding, multiple error control schemes (CRC-32, checksum), access control protocols (CSMA/CD, CSMA/CA, ALOHA variants), and sliding-window flow control (Go-Back-N, Selective Repeat). Broadcast and collision domain counts are computed and displayed for any topology.

---

## 2. System Architecture

```
flowchart LR
  subgraph client [Browser]
    UI[Next.js UI] --> Store[Zustand store]
  end
  subgraph server [Python Backend]
    API[FastAPI REST] --> PHY[Physical layer]
    API --> DLL[Data link layer]
    API --> Topo[Topology runtime]
  end
  UI -->|HTTP JSON| API
  UI -->|real-time events| WS[WebSocket]
```

The frontend communicates with the backend over HTTP for simulation requests and optionally over WebSocket for streaming events. The topology runtime handles multi-node forwarding logic (host routing, switch learning, hub flooding) when a full topology is submitted alongside a simulation request.

---

## 3. Technology Stack

| Component | Technology |
|-----------|------------|
| Frontend | Next.js 14, React 18, TypeScript, Zustand |
| Backend | Python 3, FastAPI, Pydantic v2, Uvicorn |
| Real-time | WebSockets |
| Tests | Vitest (frontend), pytest (backend) |

---

## 4. Layer Model Convention

The UI follows the **5-layer TCP/IP model**: Application, Transport, Network, Data Link, Physical. For Submission 1, only **Physical** and **Data Link** are fully implemented. The remaining layers have UI placeholders and will be completed in future submissions.

---

## 5. Functional Specification

### 5.1 Physical Layer

The physical layer accepts a message or bit string, applies a chosen line encoding, and generates signal samples that are rendered as a waveform in the UI. Supported encodings include NRZ-L, NRZ-I, Manchester, Differential Manchester, AMI, and 4B5B. Both wired and wireless media are supported.

### 5.2 Data Link Layer

The data link layer wraps messages in frames and processes them through configurable protocol stages:

| Category | Supported Options |
|----------|------------------|
| Framing | Variable-length (HDLC-style), Fixed-size |
| Error control | CRC-32, Checksum, None |
| MAC / Access control | Pure ALOHA, Slotted ALOHA, CSMA, CSMA/CD, CSMA/CA |
| Flow / ARQ | Stop-and-Wait, Go-Back-N, Selective Repeat |

### 5.3 Topology Runtime

When a topology (devices + links) is submitted, the backend runs a topology-aware simulation. Hosts route frames toward the destination, switches learn MAC addresses on ingress and forward or flood accordingly, and hubs flood to all ports except ingress. The response includes broadcast/collision domain counts and a switch learning summary.

### 5.4 Frontend — Simulator UI

The simulator UI at `/simulator` provides a topology canvas for placing and connecting devices, a waveform panel for viewing encoded signals, a DLL configuration panel for selecting protocols, an event log filterable by layer, and a Switch MAC Tables view showing learned port mappings in real time.

---

## 6. REST API Summary

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/encodings` | List available line encodings |
| GET | `/api/media` | List available media types |
| GET | `/api/datalink/options` | List Data Link layer option keys |
| POST | `/api/simulate/physical` | Run Physical layer simulation |
| POST | `/api/simulate/datalink` | Run DLL simulation (with optional topology) |
| WS | `/ws/{session_id}` | Real-time event stream |

---

## 7. Design Patterns (Backend)

| Pattern | Applied To |
|---------|-----------|
| **Strategy** | Encoding, medium, framing, error control, MAC, flow control |
| **Template Method** | Base Physical and Data Link layer classes |
| **Observer** | Layer events → WebSocket broadcast |
| **Factory** | Physical layer, Data Link layer, device creation |

---

## 8. How to Run

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
# Open http://localhost:3000/simulator
```

