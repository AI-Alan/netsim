import type { DeviceNode, NetworkLink, DeviceType } from "@/lib/types";

export type TopologyDomainStats = {
  broadcast_domains: number;
  collision_domains: number;
};

export function toBackendDeviceType(type: DeviceType): string {
  return type === "host" ? "end_host" : type;
}

/** Payload shape shared with POST /api/simulate/datalink topology fields. */
export function buildTopologyApiPayload(devices: DeviceNode[], links: NetworkLink[]) {
  return {
    topology_devices: devices.map((d) => ({
      id: d.id,
      type: toBackendDeviceType(d.type),
      label: d.label,
      mac: d.mac,
      ip: d.ip,
    })),
    topology_links: links.map((l) => ({
      id: l.id,
      src: l.src,
      dst: l.dst,
      medium: l.medium,
    })),
  };
}

export async function fetchTopologyDomainStats(
  backendBase: string,
  devices: DeviceNode[],
  links: NetworkLink[],
): Promise<TopologyDomainStats | null> {
  try {
    const body = buildTopologyApiPayload(devices, links);
    const r = await fetch(`${backendBase}/api/topology/domain-stats`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) return null;
    const data = (await r.json()) as Record<string, unknown>;
    return {
      broadcast_domains: Number(data.broadcast_domains ?? 0),
      collision_domains: Number(data.collision_domains ?? 0),
    };
  } catch {
    return null;
  }
}
