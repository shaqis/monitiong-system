export type HttpMethod = "GET" | "HEAD";

export type MonitorStatusValue = "UP" | "DOWN" | "DEGRADED" | "PENDING";

export type IntervalSeconds = 60 | 300 | 600 | 1800;

export type TimeRange = "1h" | "24h" | "7d" | "30d";

export type StatusFilter = "all" | "up" | "down" | "paused";

export interface Monitor {
  id: string;
  name: string;
  url: string;
  http_method: HttpMethod;
  interval_seconds: number;
  timeout_seconds: number;
  expected_status_code: number;
  keyword: string | null;
  check_ssl: boolean;
  is_active: boolean;
  current_status: MonitorStatusValue;
  consecutive_failures: number;
  ssl_days_remaining: number | null;
  last_checked_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface MonitorListItem extends Monitor {
  uptime_24h: number | null;
  last_response_time_ms: number | null;
}

export interface MonitorIncident {
  id: string;
  cause: string;
  started_at: string;
  resolved_at: string | null;
  duration_seconds: number;
}

export interface MonitorDetail extends MonitorListItem {
  uptime_7d: number | null;
  uptime_30d: number | null;
  recent_incidents: MonitorIncident[];
}

export interface MonitorCreateInput {
  name: string;
  url: string;
  http_method: HttpMethod;
  interval_seconds: IntervalSeconds;
  timeout_seconds: number;
  expected_status_code: number;
  keyword: string | null;
  check_ssl: boolean;
  is_active: boolean;
}

export interface MonitorUpdateInput {
  name?: string;
  url?: string;
  http_method?: HttpMethod;
  interval_seconds?: IntervalSeconds;
  timeout_seconds?: number;
  expected_status_code?: number;
  keyword?: string | null;
  check_ssl?: boolean;
  is_active?: boolean;
}

export interface Check {
  id: number;
  monitor_id: string;
  status: "UP" | "DOWN";
  status_code: number | null;
  response_time_ms: number | null;
  keyword_matched: boolean | null;
  error_message: string | null;
  checked_at: string;
}

export interface LatencyPoint {
  bucket: string;
  avg_response_time_ms: number | null;
}

export interface CheckHistoryResponse {
  items: Check[];
  total: number;
  limit: number;
  offset: number;
  series: LatencyPoint[];
}
