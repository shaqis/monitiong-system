import type {
  Check,
  CheckHistoryResponse,
  DashboardSummary,
  LoginRequest,
  LoginResponse,
  Monitor,
  MonitorCreateInput,
  MonitorDetail,
  MonitorListItem,
  MonitorUpdateInput,
  StatusFilter,
  TimeRange,
  User,
  UserCreateInput,
  UserUpdateInput,
} from "@/types";

export interface ApiFieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly fields: ApiFieldError[];

  constructor(status: number, message: string, fields: ApiFieldError[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fields = fields;
  }
}

export interface ApiRequestOptions {
  cookieHeader?: string;
  redirectOnUnauthorized?: boolean;
  signal?: AbortSignal;
}

interface RequestOptions extends ApiRequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
}

type QueryValue = string | number | undefined;

function resolveBaseUrl(): string {
  if (typeof window === "undefined") {
    return (process.env.API_INTERNAL_URL ?? "http://backend:8000/api/v1").replace(/\/$/, "");
  }
  return (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/\/$/, "");
}

function withQuery(path: string, params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseErrorBody(
  body: unknown,
  fallback: string,
): { message: string; fields: ApiFieldError[] } {
  if (isRecord(body) && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string" && detail.trim()) {
      return { message: detail, fields: [] };
    }
    if (Array.isArray(detail)) {
      const fields: ApiFieldError[] = [];
      for (const entry of detail) {
        if (!isRecord(entry)) {
          continue;
        }
        const message = typeof entry.msg === "string" ? entry.msg : "Invalid value";
        const location = Array.isArray(entry.loc) ? entry.loc : [];
        const names = location.filter((part): part is string => typeof part === "string");
        const field = names.length > 0 ? names[names.length - 1] : "";
        fields.push({ field, message });
      }
      if (fields.length > 0) {
        return { message: fields.map((field) => field.message).join("; "), fields };
      }
    }
  }
  if (typeof body === "string" && body.trim()) {
    return { message: body, fields: [] };
  }
  return { message: fallback, fields: [] };
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  if (options.cookieHeader) {
    headers.set("Cookie", options.cookieHeader);
  }
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const isServer = typeof window === "undefined";
  const response = await fetch(`${resolveBaseUrl()}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    credentials: "include",
    cache: isServer ? "no-store" : undefined,
    signal: options.signal,
  });

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text) as unknown;
    } catch {
      parsed = text;
    }
  }

  if (!response.ok) {
    const fallback = response.statusText || "Request failed";
    const { message, fields } = parseErrorBody(parsed, fallback);
    if (
      response.status === 401 &&
      !isServer &&
      options.redirectOnUnauthorized !== false
    ) {
      window.location.assign("/login");
    }
    throw new ApiError(response.status, message, fields);
  }

  return parsed as T;
}

export function login(input: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: input,
    redirectOnUnauthorized: false,
  });
}

export function logout(): Promise<void> {
  return request<void>("/auth/logout", {
    method: "POST",
    redirectOnUnauthorized: false,
  });
}

export function getCurrentUser(options?: ApiRequestOptions): Promise<User> {
  return request<User>("/auth/me", { cookieHeader: options?.cookieHeader });
}

export function getDashboardSummary(
  range: TimeRange,
  options?: ApiRequestOptions,
): Promise<DashboardSummary> {
  return request<DashboardSummary>(withQuery("/dashboard/summary", { range }), {
    cookieHeader: options?.cookieHeader,
  });
}

export interface ListMonitorsParams {
  search?: string;
  status?: StatusFilter;
}

export function listMonitors(
  params: ListMonitorsParams = {},
  options?: ApiRequestOptions,
): Promise<MonitorListItem[]> {
  return request<MonitorListItem[]>(
    withQuery("/monitors", { search: params.search, status: params.status }),
    { cookieHeader: options?.cookieHeader },
  );
}

export function getMonitor(id: string, options?: ApiRequestOptions): Promise<MonitorDetail> {
  return request<MonitorDetail>(`/monitors/${encodeURIComponent(id)}`, {
    cookieHeader: options?.cookieHeader,
  });
}

export function createMonitor(input: MonitorCreateInput): Promise<Monitor> {
  return request<Monitor>("/monitors", { method: "POST", body: input });
}

export function updateMonitor(id: string, input: MonitorUpdateInput): Promise<Monitor> {
  return request<Monitor>(`/monitors/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteMonitor(id: string): Promise<void> {
  return request<void>(`/monitors/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function checkMonitorNow(id: string): Promise<Check> {
  return request<Check>(`/monitors/${encodeURIComponent(id)}/check-now`, { method: "POST" });
}

export interface CheckHistoryParams {
  range: TimeRange;
  limit: number;
  offset: number;
}

export function getMonitorChecks(
  id: string,
  params: CheckHistoryParams,
  options?: ApiRequestOptions,
): Promise<CheckHistoryResponse> {
  return request<CheckHistoryResponse>(
    withQuery(`/monitors/${encodeURIComponent(id)}/checks`, {
      range: params.range,
      limit: params.limit,
      offset: params.offset,
    }),
    { cookieHeader: options?.cookieHeader, signal: options?.signal },
  );
}

export function listUsers(options?: ApiRequestOptions): Promise<User[]> {
  return request<User[]>("/users", { cookieHeader: options?.cookieHeader });
}

export function createUser(input: UserCreateInput): Promise<User> {
  return request<User>("/users", { method: "POST", body: input });
}

export function updateUser(id: string, input: UserUpdateInput): Promise<User> {
  return request<User>(`/users/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: input,
  });
}
