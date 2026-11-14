"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EmptyState } from "@/components/ui/empty-state";
import { formatChartTick } from "@/lib/format";
import type { LatencyPoint, TimeRange } from "@/types";

interface LatencyAreaChartProps {
  series: LatencyPoint[];
  range: TimeRange;
  emptyTitle?: string;
  emptyDescription?: string;
  height?: number;
}

export function LatencyAreaChart({
  series,
  range,
  emptyTitle = "No latency data yet",
  emptyDescription = "Latency points appear after the monitor records its first checks in this range.",
  height = 280,
}: LatencyAreaChartProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const data = series.map((point) => ({
    label: formatChartTick(point.bucket, range),
    latency: point.avg_response_time_ms,
  }));

  if (series.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }

  if (!mounted) {
    return (
      <div
        style={{ height }}
        className="w-full animate-pulse rounded-md bg-muted"
        aria-hidden="true"
      />
    );
  }

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="latency-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#2563eb" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 32% 91%)" vertical={false} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            minTickGap={24}
            tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={52}
            tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }}
            tickFormatter={(value: number) => `${value}`}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 8,
              borderColor: "hsl(214 32% 91%)",
              fontSize: 12,
            }}
            labelStyle={{ color: "hsl(222 47% 11%)" }}
            formatter={(value) => [`${String(value)} ms`, "Average latency"]}
          />
          <Area
            type="monotone"
            dataKey="latency"
            name="Average latency"
            stroke="#2563eb"
            strokeWidth={2}
            fill="url(#latency-fill)"
            connectNulls
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
