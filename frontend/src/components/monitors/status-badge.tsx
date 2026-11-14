import { Badge } from "@/components/ui/badge";
import { displayStatus } from "@/lib/format";
import type { Monitor } from "@/types";

interface StatusBadgeProps {
  monitor: Pick<Monitor, "is_active" | "current_status">;
}

export function StatusBadge({ monitor }: StatusBadgeProps) {
  const status = displayStatus(monitor);
  const variant =
    status === "UP"
      ? "success"
      : status === "DOWN"
        ? "danger"
        : status === "DEGRADED"
          ? "warning"
          : status === "PENDING"
            ? "info"
            : "muted";

  return <Badge variant={variant}>{status}</Badge>;
}
