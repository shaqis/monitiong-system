"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ApiError, createMonitor, updateMonitor } from "@/lib/api";
import { isValidHttpUrl } from "@/lib/format";
import type {
  HttpMethod,
  IntervalSeconds,
  MonitorCreateInput,
  MonitorListItem,
} from "@/types";

interface MonitorFormModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  monitor?: MonitorListItem | null;
  onSaved: () => void;
}

interface FormState {
  name: string;
  url: string;
  httpMethod: HttpMethod;
  intervalSeconds: IntervalSeconds;
  timeoutSeconds: string;
  expectedStatus: string;
  keyword: string;
  checkSsl: boolean;
}

const INTERVALS: Array<{ value: IntervalSeconds; label: string }> = [
  { value: 60, label: "1 minute" },
  { value: 300, label: "5 minutes" },
  { value: 600, label: "10 minutes" },
  { value: 1800, label: "30 minutes" },
];

function emptyState(): FormState {
  return {
    name: "",
    url: "",
    httpMethod: "GET",
    intervalSeconds: 60,
    timeoutSeconds: "10",
    expectedStatus: "200",
    keyword: "",
    checkSsl: true,
  };
}

function stateFromMonitor(monitor: MonitorListItem): FormState {
  return {
    name: monitor.name,
    url: monitor.url,
    httpMethod: monitor.http_method,
    intervalSeconds:
      monitor.interval_seconds === 300 ||
      monitor.interval_seconds === 600 ||
      monitor.interval_seconds === 1800
        ? monitor.interval_seconds
        : 60,
    timeoutSeconds: String(monitor.timeout_seconds),
    expectedStatus: String(monitor.expected_status_code),
    keyword: monitor.keyword ?? "",
    checkSsl: monitor.check_ssl,
  };
}

function toInterval(value: string): IntervalSeconds {
  if (value === "300") {
    return 300;
  }
  if (value === "600") {
    return 600;
  }
  if (value === "1800") {
    return 1800;
  }
  return 60;
}

export function MonitorFormModal({
  open,
  onOpenChange,
  monitor,
  onSaved,
}: MonitorFormModalProps) {
  const [form, setForm] = useState<FormState>(emptyState);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(monitor ? stateFromMonitor(monitor) : emptyState());
      setError(null);
      setFieldErrors({});
    }
  }, [open, monitor]);

  const headWithKeyword = form.httpMethod === "HEAD" && form.keyword.trim().length > 0;

  const timeoutOptions = Array.from(
    new Set([5, 10, 15, 20, 25, 30, monitor?.timeout_seconds ?? 10]),
  ).sort((left, right) => left - right);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }

  function validate(): { input?: MonitorCreateInput; errors: Record<string, string> } {
    const errors: Record<string, string> = {};
    const name = form.name.trim();
    const url = form.url.trim();
    const keyword = form.keyword.trim();
    const timeout = Number(form.timeoutSeconds);
    const expected = Number(form.expectedStatus);

    if (!name) {
      errors.name = "Display name is required.";
    } else if (name.length > 120) {
      errors.name = "Display name must be at most 120 characters.";
    }

    if (!isValidHttpUrl(url)) {
      errors.url = "Enter a valid URL that starts with http:// or https://.";
    } else if (url.length > 2048) {
      errors.url = "URL must be at most 2048 characters.";
    }

    if (!Number.isInteger(timeout) || timeout < 5 || timeout > 30) {
      errors.timeoutSeconds = "Timeout must be between 5 and 30 seconds.";
    }

    if (!Number.isInteger(expected) || expected < 100 || expected > 599) {
      errors.expectedStatus = "Expected status must be between 100 and 599.";
    }

    if (keyword.length > 255) {
      errors.keyword = "Keyword must be at most 255 characters.";
    }

    if (Object.keys(errors).length > 0) {
      return { errors };
    }

    return {
      errors,
      input: {
        name,
        url,
        http_method: form.httpMethod,
        interval_seconds: form.intervalSeconds,
        timeout_seconds: timeout,
        expected_status_code: expected,
        keyword: keyword.length > 0 ? keyword : null,
        check_ssl: form.checkSsl,
        is_active: monitor ? monitor.is_active : true,
      },
    };
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const result = validate();
    setFieldErrors(result.errors);
    if (!result.input) {
      return;
    }

    setSaving(true);
    try {
      if (monitor) {
        await updateMonitor(monitor.id, result.input);
      } else {
        await createMonitor(result.input);
      }
      onOpenChange(false);
      onSaved();
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
        const mapped: Record<string, string> = {};
        for (const field of caught.fields) {
          if (field.field) {
            mapped[field.field] = field.message;
          }
        }
        setFieldErrors(mapped);
      } else {
        setError("Unable to save the monitor. Try again.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{monitor ? "Edit URL" : "Add URL"}</DialogTitle>
          <DialogDescription>
            {monitor
              ? "Update the check configuration. Changing the target resets its status to pending."
              : "Configure a new URL for periodic availability and latency checks."}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit}>
          {error ? (
            <Alert variant="destructive">
              <div>
                <AlertTitle>Could not save</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </div>
            </Alert>
          ) : null}

          {headWithKeyword ? (
            <Alert variant="warning">
              <div>
                <AlertTitle>HEAD cannot verify a keyword</AlertTitle>
                <AlertDescription>
                  A HEAD request has no response body, so the keyword check will fail. Use GET if
                  the content keyword matters.
                </AlertDescription>
              </div>
            </Alert>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="monitor-name">Display name</Label>
            <Input
              id="monitor-name"
              value={form.name}
              onChange={(event) => update("name", event.target.value)}
              placeholder="Production portal"
              disabled={saving}
              maxLength={120}
            />
            {fieldErrors.name ? (
              <p className="text-xs text-red-600">{fieldErrors.name}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="monitor-url">Target URL</Label>
            <Input
              id="monitor-url"
              value={form.url}
              onChange={(event) => update("url", event.target.value)}
              placeholder="https://example.com/health"
              disabled={saving}
              inputMode="url"
            />
            {fieldErrors.url ? <p className="text-xs text-red-600">{fieldErrors.url}</p> : null}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="monitor-method">HTTP method</Label>
              <Select
                value={form.httpMethod}
                onValueChange={(value) =>
                  update("httpMethod", value === "HEAD" ? "HEAD" : "GET")
                }
                disabled={saving}
              >
                <SelectTrigger id="monitor-method">
                  <SelectValue placeholder="Select method" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="GET">GET</SelectItem>
                  <SelectItem value="HEAD">HEAD</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="monitor-interval">Check interval</Label>
              <Select
                value={String(form.intervalSeconds)}
                onValueChange={(value) => update("intervalSeconds", toInterval(value))}
                disabled={saving}
              >
                <SelectTrigger id="monitor-interval">
                  <SelectValue placeholder="Select interval" />
                </SelectTrigger>
                <SelectContent>
                  {INTERVALS.map((interval) => (
                    <SelectItem key={interval.value} value={String(interval.value)}>
                      {interval.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="monitor-timeout">Timeout (seconds)</Label>
              <Select
                value={form.timeoutSeconds}
                onValueChange={(value) => update("timeoutSeconds", value)}
                disabled={saving}
              >
                <SelectTrigger id="monitor-timeout">
                  <SelectValue placeholder="Select timeout" />
                </SelectTrigger>
                <SelectContent>
                  {timeoutOptions.map((timeout) => (
                    <SelectItem key={timeout} value={String(timeout)}>
                      {timeout} seconds
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {fieldErrors.timeout_seconds ? (
                <p className="text-xs text-red-600">{fieldErrors.timeout_seconds}</p>
              ) : fieldErrors.timeoutSeconds ? (
                <p className="text-xs text-red-600">{fieldErrors.timeoutSeconds}</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="monitor-expected">Expected status code</Label>
              <Input
                id="monitor-expected"
                type="number"
                min={100}
                max={599}
                value={form.expectedStatus}
                onChange={(event) => update("expectedStatus", event.target.value)}
                disabled={saving}
              />
              {fieldErrors.expected_status_code ? (
                <p className="text-xs text-red-600">{fieldErrors.expected_status_code}</p>
              ) : fieldErrors.expectedStatus ? (
                <p className="text-xs text-red-600">{fieldErrors.expectedStatus}</p>
              ) : null}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="monitor-keyword">Content keyword (optional)</Label>
            <Input
              id="monitor-keyword"
              value={form.keyword}
              onChange={(event) => update("keyword", event.target.value)}
              placeholder="Sign in"
              disabled={saving}
              maxLength={255}
            />
            <p className="text-xs text-muted-foreground">
              The response body must contain this text for the check to pass.
            </p>
            {fieldErrors.keyword ? <p className="text-xs text-red-600">{fieldErrors.keyword}</p> : null}
          </div>

          <div className="flex items-center justify-between rounded-lg border p-3">
            <div className="space-y-0.5">
              <Label htmlFor="monitor-ssl">Check SSL certificate</Label>
              <p className="text-xs text-muted-foreground">
                Inspect the peer certificate expiry for HTTPS URLs.
              </p>
            </div>
            <Switch
              id="monitor-ssl"
              checked={form.checkSsl}
              onCheckedChange={(checked) => update("checkSsl", checked)}
              disabled={saving}
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden="true" />
                  Saving…
                </>
              ) : monitor ? (
                "Save changes"
              ) : (
                "Create URL"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
