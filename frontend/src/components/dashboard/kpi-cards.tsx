import { Activity, Gauge, Link2, Timer } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatLatency, formatUptime, uptimeTone } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DashboardSummary } from "@/types";

interface KpiCardsProps {
  summary: DashboardSummary;
}

export function KpiCards({ summary }: KpiCardsProps) {
  const cards = [
    {
      title: "Monitored URLs",
      value: summary.total_monitors.toString(),
      detail: `${summary.active_monitors} active · ${summary.paused_monitors} paused`,
      icon: Link2,
      tone: "text-sky-600",
    },
    {
      title: "Operational health",
      value: `${summary.up_count} up`,
      detail: `${summary.down_count} down · ${summary.pending_count} pending`,
      icon: Activity,
      tone: summary.down_count > 0 ? "text-red-600" : "text-emerald-600",
    },
    {
      title: "Overall uptime",
      value: formatUptime(summary.overall_uptime),
      detail: "Across the selected range",
      icon: Gauge,
      tone: uptimeTone(summary.overall_uptime),
    },
    {
      title: "Average response",
      value: formatLatency(summary.avg_response_time_ms),
      detail: "Across the selected range",
      icon: Timer,
      tone: "text-indigo-600",
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <Card key={card.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {card.title}
              </CardTitle>
              <Icon className={cn("h-4 w-4", card.tone)} aria-hidden="true" />
            </CardHeader>
            <CardContent>
              <p className={cn("text-2xl font-semibold tracking-tight", card.tone)}>
                {card.value}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">{card.detail}</p>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
