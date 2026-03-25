"use client";

import { useEffect, useState } from "react";
import type { DeviceNode, NetworkLink } from "@/lib/types";
import { fetchTopologyDomainStats, type TopologyDomainStats } from "@/lib/topologyDomainStats";

const DEBOUNCE_MS = 260;

/**
 * Keeps broadcast/collision domain counts in sync with the canvas whenever devices or links change.
 * Uses the same backend rules as topology-mode simulation (single source of truth).
 */
export function useTopologyDomainStats(
  backendBase: string,
  backendReachable: boolean,
  devices: DeviceNode[],
  links: NetworkLink[],
): TopologyDomainStats | null {
  const [stats, setStats] = useState<TopologyDomainStats | null>(null);

  useEffect(() => {
    if (!backendReachable) {
      setStats(null);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      void (async () => {
        const next = await fetchTopologyDomainStats(backendBase, devices, links);
        if (!cancelled) setStats(next);
      })();
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [backendBase, backendReachable, devices, links]);

  return stats;
}
