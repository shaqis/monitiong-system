import Link from "next/link";
import { Info } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { IncidentsTable } from "@/components/dashboard/incidents-table";
import { KpiCards } from "@/components/dashboard/kpi-cards";
import { RangeSelector } from "@/components/dashboard/range-selector";
import { StatusBars, StatusBarsLegend } from "@/components/dashboard/status-bars";
import { LatencyAreaChart } from "@/components/charts/latency-area-chart";
import { getDashboardSummary } from "@/lib/api";
import { normalizeTimeRange } from "@/lib/params";
import { getCookieHeader, getRequiredUser } from "@/lib/server-session";
import { firstParam } from "@/lib/utils";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Dashboard",
};

interface DashboardPageProps {
  searchParams: { range?: string | string[] };
}

export default async function DashboardPage({ searchParams }: DashboardPageProps) {
  const range = normalizeTimeRange(firstParam(searchParams.range));
  await getRequiredUser();
  const summary = await getDashboardSummary(range, { cookieHeader: getCookieHeader() });

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Operational overview</h2>
          <p className="text-sm text-muted-foreground">
            Availability, latency, and incidents for every monitored URL.
          </p>
        </div>
        <RangeSelector value={range} />
      </div>

      {summary.total_monitors === 0 ? (
        <Alert variant="info">
          <div className="space-y-3">
            <div>
              <AlertTitle>No monitors configured</AlertTitle>
              <AlertDescription>
                The dashboard is empty because no URLs are monitored yet. Add the first URL to
                start collecting checks.
              </AlertDescription>
            </div>
            <Button asChild variant="outline" size="sm">
              <Link href="/urls">Go to URLs</Link>
            </Button>
          </div>
        </Alert>
      ) : null}

      <KpiCards summary={summary} />

      <Card>
        <CardHeader>
          <CardTitle>Response latency trend</CardTitle>
          <CardDescription>Average response time across all monitors.</CardDescription>
        </CardHeader>
        <CardContent>
          <LatencyAreaChart
            series={summary.latency_series}
            range={range}
            emptyTitle="No latency samples in this range"
            emptyDescription="Checks are collected on the monitor interval. Pick a wider range or wait for the next check."
          />
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Recent incidents</CardTitle>
            <CardDescription>Active and recently resolved downtime events.</CardDescription>
          </CardHeader>
          <CardContent>
            <IncidentsTable incidents={summary.incidents} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Uptime and status</CardTitle>
            <CardDescription>Recent check intervals for each monitor.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <StatusBars monitors={summary.monitors} />
            <StatusBarsLegend />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
