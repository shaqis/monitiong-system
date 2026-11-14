import type { StatusFilter, TimeRange } from "@/types";

const TIME_RANGES: TimeRange[] = ["1h", "24h", "7d", "30d"];
const STATUS_FILTERS: StatusFilter[] = ["all", "up", "down", "paused"];

export function normalizeTimeRange(value: string | undefined): TimeRange {
  if (value && (TIME_RANGES as string[]).includes(value)) {
    return value as TimeRange;
  }
  return "24h";
}

export function normalizeStatusFilter(value: string | undefined): StatusFilter {
  if (value && (STATUS_FILTERS as string[]).includes(value)) {
    return value as StatusFilter;
  }
  return "all";
}
