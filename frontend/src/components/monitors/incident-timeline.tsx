import { CheckCircle2, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { IncidentSummary } from "@/types";

interface IncidentTimelineProps {
  incidents: IncidentSummary[];
}

export function IncidentTimeline({ incidents }: IncidentTimelineProps) {
  if (incidents.length === 0) {
    return (
      <EmptyState
        title="No incidents recorded"
        description="This monitor has not had an outage in the last 30 days."
        icon={<CheckCircle2 className="h-6 w-6 text-emerald-500" aria-hidden="true" />}
      />
    );
  }

  return (
    <ol className="relative space-y-6 border-l pl-6">
      {incidents.map((incident) => (
        <li key={incident.id} className="relative">
          <span
            className={`absolute -left-[1.9rem] top-1.5 flex h-3 w-3 rounded-full border-2 border-white ${
              incident.resolved_at ? "bg-emerald-500" : "bg-red-500"
            }`}
            aria-hidden="true"
          />
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{incident.cause}</span>
              {incident.resolved_at ? (
                <Badge variant="success">Resolved</Badge>
              ) : (
                <Badge variant="danger">Ongoing</Badge>
              )}
            </div>
            <p className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                Started {formatDateTime(incident.started_at)}
              </span>
              <span>Duration {formatDuration(incident.duration_seconds)}</span>
              {incident.resolved_at ? (
                <span>Resolved {formatDateTime(incident.resolved_at)}</span>
              ) : null}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
