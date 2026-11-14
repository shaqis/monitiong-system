import type { IntervalSeconds, Monitor, TimeRange } from "@/types";

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

function pad(value: number): string {
  return value.toString().padStart(2, "0");
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date;
}

export function formatDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) {
    return "—";
  }
  return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}, ${date.getUTCFullYear()} ${pad(
    date.getUTCHours(),
  )}:${pad(date.getUTCMinutes())} UTC`;
}

export function formatShortDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) {
    return "—";
  }
  return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()} ${pad(date.getUTCHours())}:${pad(
    date.getUTCMinutes(),
  )}`;
}

export function formatChartTick(value: string, range: TimeRange): string {
  const date = parseDate(value);
  if (!date) {
    return "—";
  }
  if (range === "7d" || range === "30d") {
    return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}`;
  }
  return `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
}

export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m ${seconds % 60}s`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}h ${minutes % 60}m`;
  }
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

export function formatInterval(seconds: number): string {
  const labels: Record<IntervalSeconds, string> = {
    60: "1m",
    300: "5m",
    600: "10m",
    1800: "30m",
  };
  if (seconds === 60 || seconds === 300 || seconds === 600 || seconds === 1800) {
    return labels[seconds];
  }
  return `${seconds}s`;
}

export function formatUptime(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return `${value.toFixed(2)}%`;
}

export function formatLatency(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return `${Math.round(value)} ms`;
}

export function formatSslDays(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (value <= 0) {
    return "Expired";
  }
  return `${value}d`;
}

export function uptimeTone(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "text-muted-foreground";
  }
  if (value >= 99.5) {
    return "text-emerald-600";
  }
  if (value >= 95) {
    return "text-amber-600";
  }
  return "text-red-600";
}

export function sslTone(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "text-muted-foreground";
  }
  if (value <= 0) {
    return "text-red-600";
  }
  if (value <= 30) {
    return "text-amber-600";
  }
  return "text-emerald-600";
}

export function displayStatus(monitor: Pick<Monitor, "is_active" | "current_status">): string {
  if (!monitor.is_active) {
    return "PAUSED";
  }
  return monitor.current_status;
}

export function isValidHttpUrl(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
    return false;
  }
  try {
    const parsed = new URL(trimmed);
    return parsed.hostname.length > 0;
  } catch {
    return false;
  }
}

export function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

export function passwordByteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}
