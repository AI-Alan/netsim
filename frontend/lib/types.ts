export type EventType =
  | "BITS_SENT" | "SIGNAL_DRAWN" | "BITS_RECEIVED"
  | "FRAME_SENT" | "FRAME_RECEIVED" | "FRAME_DROPPED"
  | "ARP_REQUEST" | "ARP_REPLY"
  | "FRAMING_INFO" | "ERROR_DETECTED" | "ACCESS_CONTROL"
  | "FLOW_CONTROL" | "ACK_SENT" | "NAK_SENT" | "WINDOW_UPDATE"
  | "PACKET_SENT" | "PACKET_RECEIVED" | "ROUTING_LOOKUP" | "TTL_EXPIRED"
  | "SEGMENT_SENT" | "SEGMENT_RECEIVED" | "TCP_STATE"
  | "APP_REQUEST" | "APP_RESPONSE" | "APP_ENCODING" | "SESSION_INFO"
  | "SIM_PAUSED" | "SIM_RESUMED" | "SIM_STEPPED" | "SIM_RESET";

// TCP/IP model — no separate session/presentation
export type LayerName =
  | "physical" | "datalink" | "network" | "transport" | "application" | "engine";

export interface PDU {
  type: string;
  headers: Record<string, unknown>;
  payload: string;
}

export interface SignalData {
  samples: number[];
  sample_rate: number;
  encoding: string;
}

export interface SimEvent {
  event_id:   string;
  timestamp:  number;
  event_type: EventType;
  layer:      LayerName;
  src_device: string;
  dst_device: string | null;
  pdu:        PDU;
  signal:     SignalData | null;
  meta:       Record<string, unknown>;
}

export type DeviceType = "computer" | "server" | "router" | "switch" | "hub" | "laptop";
export type MediumType = "wired" | "wireless";

export interface DeviceNode {
  id:     string;
  type:   DeviceType;
  label:  string;
  mac:    string;
  ip:     string;
  x:      number;
  y:      number;
  layers: number;
  medium?: MediumType;
}

export interface NetworkLink {
  id:     string;
  src:    string;
  dst:    string;
  medium: MediumType;
}
