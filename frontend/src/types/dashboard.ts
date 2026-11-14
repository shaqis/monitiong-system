import type { LatencyPoint, MonitorStatusValue } from "./monitor";

export interface MonitorStatusStrip {
  id: string;
  name: string;
  url: string;
  is_active: boolean;
  current_status: MonitorStatusValue;
  ssl_days_remaining: number | null;
  recent_statuses: Array<"UP" | "DOWN">;
}

export interface IncidentSummary {
  id: string;
  monitor_id: string;
  monitor_name: string;
  cause: string;
  started_at: string;
  resolved_at: string | null;
  duration_seconds: number;
}

export interface DashboardSummary {
  total_monitors: number;
  active_monitors: number;
  paused_monitors: number;
  up_count: number;
  down_count: number;
  pending_count: number;
  overall_uptime: number | null;
  avg_response_time_ms: number | null;
  latency_series: LatencyPoint[];
  monitors: MonitorStatusStrip[];
  incidents: IncidentSummary[];
}
