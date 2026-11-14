import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckHistoryPanel } from "@/components/monitors/check-history-panel";
import { IncidentTimeline } from "@/components/monitors/incident-timeline";
import { MonitorActions } from "@/components/monitors/monitor-actions";
import { StatusBadge } from "@/components/monitors/status-badge";
import { UptimeMeter } from "@/components/monitors/uptime-meter";
import { ApiError, getMonitor, getMonitorChecks } from "@/lib/api";
import {
  formatDateTime,
  formatInterval,
  formatSslDays,
  sslTone,
} from "@/lib/format";
import { getCookieHeader, getRequiredUser } from "@/lib/server-session";
import { cn } from "@/lib/utils";
import type { MonitorDetail } from "@/types";

export const dynamic = "force-dynamic";

interface MonitorDetailPageProps {
  params: { id: string };
}

function sslBadgeVariant(days: number | null): "success" | "warning" | "danger" | "muted" {
  if (days === null) {
    return "muted";
  }
  if (days <= 0) {
    return "danger";
  }
  if (days <= 30) {
    return "warning";
  }
  return "success";
}

export default async function MonitorDetailPage({ params }: MonitorDetailPageProps) {
  const user = await getRequiredUser();
  const cookieHeader = getCookieHeader();

  let monitor: MonitorDetail;
  try {
    monitor = await getMonitor(params.id, { cookieHeader });
  } catch (error) {
    if (error instanceof ApiError && [400, 404, 422].includes(error.status)) {
      notFound();
    }
    throw error;
  }

  const checks = await getMonitorChecks(
    params.id,
    { range: "24h", limit: 25, offset: 0 },
    { cookieHeader },
  );

  const incidents = monitor.recent_incidents;
  const isAdmin = user.role === "admin";

  const uptimeStats = [
    { label: "24 hours", value: monitor.uptime_24h },
    { label: "7 days", value: monitor.uptime_7d },
    { label: "30 days", value: monitor.uptime_30d },
  ];

  return (
    <div className="space-y-6">
      <Link
        href="/urls"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Back to URLs
      </Link>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-2xl font-semibold tracking-tight">{monitor.name}</h2>
            <StatusBadge monitor={monitor} />
            {!monitor.is_active ? <Badge variant="muted">Paused</Badge> : null}
          </div>
          <a
            href={monitor.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex max-w-full items-center gap-1 text-sm text-muted-foreground hover:underline"
          >
            <span className="truncate">{monitor.url}</span>
            <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          </a>
        </div>
        {isAdmin ? <MonitorActions monitor={monitor} /> : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {uptimeStats.map((stat) => (
          <Card key={stat.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Uptime · {stat.label}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <UptimeMeter value={stat.value} />
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
            <CardDescription>Probe rules applied by the scheduler.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <div>
                <dt className="text-muted-foreground">Method</dt>
                <dd className="font-medium">{monitor.http_method}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Interval</dt>
                <dd className="font-medium">{formatInterval(monitor.interval_seconds)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Timeout</dt>
                <dd className="font-medium">{monitor.timeout_seconds}s</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Expected status</dt>
                <dd className="font-medium">{monitor.expected_status_code}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-muted-foreground">Content keyword</dt>
                <dd className="break-words font-medium">{monitor.keyword ?? "None"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">SSL checks</dt>
                <dd className="font-medium">{monitor.check_ssl ? "Enabled" : "Disabled"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Consecutive failures</dt>
                <dd className="font-medium">{monitor.consecutive_failures}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-muted-foreground">Last checked</dt>
                <dd className="font-medium">{formatDateTime(monitor.last_checked_at)}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-muted-foreground">Created</dt>
                <dd className="font-medium">{formatDateTime(monitor.created_at)}</dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>SSL certificate</CardTitle>
            <CardDescription>Peer certificate expiry for HTTPS targets.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-3">
              <ShieldCheck
                className={cn("h-8 w-8", sslTone(monitor.ssl_days_remaining))}
                aria-hidden="true"
              />
              <div>
                <p className={cn("text-lg font-semibold", sslTone(monitor.ssl_days_remaining))}>
                  {formatSslDays(monitor.ssl_days_remaining)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {monitor.ssl_days_remaining === null
                    ? "Not inspected or not an HTTPS URL."
                    : monitor.ssl_days_remaining <= 0
                      ? "The certificate has expired."
                      : "Days remaining before expiry."}
                </p>
              </div>
            </div>
            <Badge variant={sslBadgeVariant(monitor.ssl_days_remaining)}>
              {monitor.ssl_days_remaining === null
                ? "SSL unknown"
                : monitor.ssl_days_remaining <= 0
                  ? "SSL expired"
                  : "SSL valid"}
            </Badge>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Incident timeline</CardTitle>
            <CardDescription>Downtime events from the last 30 days.</CardDescription>
          </CardHeader>
          <CardContent>
            <IncidentTimeline incidents={incidents} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="pt-6">
          <CheckHistoryPanel
            monitorId={monitor.id}
            initialData={checks}
            initialRange="24h"
          />
        </CardContent>
      </Card>
    </div>
  );
}
