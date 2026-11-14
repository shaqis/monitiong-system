"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LatencyAreaChart } from "@/components/charts/latency-area-chart";
import { ApiError, getMonitorChecks } from "@/lib/api";
import { formatDateTime, formatLatency } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CheckHistoryResponse, TimeRange } from "@/types";

const RANGES: Array<{ value: TimeRange; label: string }> = [
  { value: "24h", label: "24H" },
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
];

interface CheckHistoryPanelProps {
  monitorId: string;
  initialData: CheckHistoryResponse;
  initialRange: TimeRange;
}

export function CheckHistoryPanel({
  monitorId,
  initialData,
  initialRange,
}: CheckHistoryPanelProps) {
  const [range, setRange] = useState<TimeRange>(initialRange);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<CheckHistoryResponse>(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const initialKey = useRef(`${initialRange}:0`);
  const [loadedKey, setLoadedKey] = useState(initialKey.current);
  const limit = data.limit;

  useEffect(() => {
    const key = `${range}:${offset}`;
    if (key === loadedKey && reloadKey === 0) {
      return;
    }

    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);

    getMonitorChecks(
      monitorId,
      { range, limit, offset },
      { signal: controller.signal },
    )
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setLoadedKey(key);
          setReloadKey(0);
        }
      })
      .catch((caught: unknown) => {
        if (cancelled) {
          return;
        }
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        setError(
          caught instanceof ApiError ? caught.message : "The check history request failed.",
        );
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [monitorId, range, offset, limit, loadedKey, reloadKey]);

  function changeRange(next: TimeRange) {
    if (next === range) {
      return;
    }
    setOffset(0);
    setRange(next);
  }

  const page = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(data.total / limit));
  const firstRow = data.total === 0 ? 0 : offset + 1;
  const lastRow = Math.min(offset + data.items.length, data.total);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-lg font-semibold tracking-tight">Response and check history</h3>
          <p className="text-sm text-muted-foreground">
            Average response time and raw probe results.
          </p>
        </div>
        <div className="inline-flex items-center rounded-md border bg-white p-1">
          {RANGES.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => changeRange(option.value)}
              aria-pressed={range === option.value}
              disabled={loading}
              className={cn(
                "rounded px-3 py-1.5 text-xs font-semibold transition-colors",
                range === option.value
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <ErrorState
          title="Check history could not load"
          message={error}
          onRetry={() => setReloadKey((value) => value + 1)}
        />
      ) : loading ? (
        <div className="space-y-4" aria-busy="true" aria-label="Loading check history">
          <Skeleton className="h-[280px] w-full rounded-xl" />
          <Skeleton className="h-40 w-full rounded-xl" />
        </div>
      ) : (
        <>
          <LatencyAreaChart
            series={data.series}
            range={range}
            emptyTitle="No latency samples in this range"
            emptyDescription="Pick a wider range or wait for the next scheduled check."
          />

          {data.items.length === 0 ? (
            <EmptyState
              title="No checks recorded"
              description="This range has no probe results yet. Run a check now or wait for the scheduler."
            />
          ) : (
            <>
              <div className="rounded-xl border bg-white">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Checked</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>HTTP</TableHead>
                      <TableHead>Latency</TableHead>
                      <TableHead>Keyword</TableHead>
                      <TableHead>Error</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.items.map((check) => (
                      <TableRow key={check.id}>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {formatDateTime(check.checked_at)}
                        </TableCell>
                        <TableCell>
                          <Badge variant={check.status === "UP" ? "success" : "danger"}>
                            {check.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {check.status_code ?? "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {formatLatency(check.response_time_ms)}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {check.keyword_matched === null
                            ? "—"
                            : check.keyword_matched
                              ? "Matched"
                              : "Missing"}
                        </TableCell>
                        <TableCell
                          className="max-w-[20rem] truncate text-muted-foreground"
                          title={check.error_message ?? undefined}
                        >
                          {check.error_message ?? "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <div className="flex flex-col items-center justify-between gap-2 text-sm text-muted-foreground sm:flex-row">
                <span>
                  Showing {firstRow}–{lastRow} of {data.total} checks
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setOffset(Math.max(0, offset - limit))}
                    disabled={offset === 0}
                  >
                    <ChevronLeft aria-hidden="true" />
                    Previous
                  </Button>
                  <span className="text-xs">
                    Page {page} of {totalPages}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setOffset(offset + limit)}
                    disabled={offset + limit >= data.total}
                  >
                    Next
                    <ChevronRight aria-hidden="true" />
                  </Button>
                </div>
              </div>
            </>
          )}
        </>
      )}

      {loading ? (
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          Loading checks…
        </span>
      ) : null}
    </div>
  );
}
