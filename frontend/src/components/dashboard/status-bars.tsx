import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { displayStatus, formatSslDays, sslTone } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { MonitorStatusStrip } from "@/types";

interface StatusBarsProps {
  monitors: MonitorStatusStrip[];
}

export function StatusBars({ monitors }: StatusBarsProps) {
  if (monitors.length === 0) {
    return (
      <EmptyState
        title="No monitors to display"
        description="Add a URL to see its recent check history here."
      />
    );
  }

  return (
    <ul className="space-y-4">
      {monitors.map((monitor) => {
        const status = displayStatus(monitor);
        const paused = !monitor.is_active;
        return (
          <li key={monitor.id} className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Link
                href={`/urls/${monitor.id}`}
                className="truncate text-sm font-medium hover:underline"
              >
                {monitor.name}
              </Link>
              <div className="flex items-center gap-2">
                <span className={cn("text-xs", sslTone(monitor.ssl_days_remaining))}>
                  SSL {formatSslDays(monitor.ssl_days_remaining)}
                </span>
                <Badge
                  variant={
                    status === "UP"
                      ? "success"
                      : status === "DOWN"
                        ? "danger"
                        : status === "DEGRADED"
                          ? "warning"
                          : "muted"
                  }
                >
                  {status}
                </Badge>
              </div>
            </div>
            <div className="flex items-center gap-1" aria-label={`Recent checks for ${monitor.name}`}>
              {monitor.recent_statuses.length === 0 ? (
                <span className="text-xs text-muted-foreground">
                  {paused ? "Paused — no recent checks" : "No checks recorded yet"}
                </span>
              ) : (
                monitor.recent_statuses.map((entry, index) => (
                  <span
                    key={`${monitor.id}-${index}`}
                    title={paused ? "Paused" : entry}
                    className={cn(
                      "h-2.5 w-2.5 rounded-sm",
                      paused
                        ? "bg-slate-300"
                        : entry === "UP"
                          ? "bg-emerald-500"
                          : "bg-red-500",
                    )}
                  />
                ))
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function StatusBarsLegend() {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1">
        <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" aria-hidden="true" />
        Up
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="h-2.5 w-2.5 rounded-sm bg-red-500" aria-hidden="true" />
        Down
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="h-2.5 w-2.5 rounded-sm bg-slate-300" aria-hidden="true" />
        Paused / no data
      </span>
    </div>
  );
}
