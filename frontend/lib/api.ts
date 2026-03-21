/**
 * Backend discovery — keeps UI options in sync with FastAPI factories.
 */
const backendBase = () => process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export type DatalinkApiOptions = {
  framing: string[];
  error: string[];
  mac_proto: string[];
  flow: string[];
};

export const FALLBACK_ENCODINGS = [
  "NRZ-L",
  "NRZ-I",
  "Manchester",
  "Differential Manchester",
  "AMI",
  "4B5B",
] as const;

export const FALLBACK_MEDIA = ["wired", "wireless"] as const;

export const FALLBACK_DATALINK: DatalinkApiOptions = {
  framing: ["variable", "fixed"],
  error: ["crc32", "checksum", "none"],
  mac_proto: ["csma_cd", "csma_ca", "csma", "pure_aloha", "slotted_aloha"],
  flow: ["stop_and_wait", "go_back_n", "selective_repeat"],
};

export async function fetchBackendHealth(): Promise<boolean> {
  try {
    const r = await fetch(`${backendBase()}/health`, { method: "GET" });
    return r.ok;
  } catch {
    return false;
  }
}

export async function fetchSimOptions(): Promise<{
  encodings: string[];
  media: string[];
  datalink: DatalinkApiOptions;
} | null> {
  try {
    const [encR, medR, dlR] = await Promise.all([
      fetch(`${backendBase()}/api/encodings`),
      fetch(`${backendBase()}/api/media`),
      fetch(`${backendBase()}/api/datalink/options`),
    ]);
    if (!encR.ok || !medR.ok || !dlR.ok) return null;
    const enc = await encR.json();
    const med = await medR.json();
    const dl = await dlR.json();
    return {
      encodings: Array.isArray(enc.encodings) ? enc.encodings : [...FALLBACK_ENCODINGS],
      media: Array.isArray(med.media) ? med.media : [...FALLBACK_MEDIA],
      datalink: {
        framing: Array.isArray(dl.framing) ? dl.framing : [...FALLBACK_DATALINK.framing],
        error: Array.isArray(dl.error) ? dl.error : [...FALLBACK_DATALINK.error],
        mac_proto: Array.isArray(dl.mac_proto) ? dl.mac_proto : [...FALLBACK_DATALINK.mac_proto],
        flow: Array.isArray(dl.flow) ? dl.flow : [...FALLBACK_DATALINK.flow],
      },
    };
  } catch {
    return null;
  }
}

/** Short educational labels for registry keys (fallback to prettified key). */
export function labelDatalinkOption(kind: keyof DatalinkApiOptions, value: string): string {
  const maps: Record<string, Record<string, string>> = {
    framing: {
      variable: "Variable — HDLC-style flags + byte stuffing",
      fixed: "Fixed-size frames (padded / truncated)",
    },
    error: {
      crc32: "CRC-32 (IEEE 802.3)",
      checksum: "Checksum-16 (RFC 1071)",
      none: "None (no detection)",
    },
    mac_proto: {
      csma_cd: "CSMA/CD — Ethernet-style backoff",
      csma_ca: "CSMA/CA — Wi-Fi-style DCF (+ optional RTS/CTS)",
      csma: "CSMA — 1-persistent",
      pure_aloha: "Pure ALOHA",
      slotted_aloha: "Slotted ALOHA",
    },
    flow: {
      stop_and_wait: "Stop-and-Wait ARQ",
      go_back_n: "Go-Back-N ARQ",
      selective_repeat: "Selective Repeat ARQ",
    },
  };
  return maps[kind]?.[value] ?? value.replace(/_/g, " ");
}
