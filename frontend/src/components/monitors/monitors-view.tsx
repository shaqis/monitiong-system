"use client";

import { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Loader2,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MonitorFormModal } from "@/components/monitors/monitor-form-modal";
import { StatusBadge } from "@/components/monitors/status-badge";
import { UptimeMeter } from "@/components/monitors/uptime-meter";
import {
  ApiError,
  checkMonitorNow,
  deleteMonitor,
  updateMonitor,
} from "@/lib/api";
import {
  formatInterval,
  formatLatency,
  formatSslDays,
  sslTone,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import type { MonitorListItem, StatusFilter } from "@/types";

interface MonitorsViewProps {
  monitors: MonitorListItem[];
  isAdmin: boolean;
  initialSearch: string;
  initialStatus: StatusFilter;
}

interface Feedback {
  variant: "success" | "warning" | "destructive";
  title: string;
  body: string;
}

function feedbackFromError(caught: unknown): Feedback {
  if (caught instanceof ApiError) {
    return { variant: "destructive", title: "Action failed", body: caught.message };
  }
  return { variant: "destructive", title: "Action failed", body: "The request could not be completed." };
}

function buildUrl(search: string, status: StatusFilter): string {
  const params = new URLSearchParams();
  if (search) {
    params.set("q", search);
  }
  if (status !== "all") {
    params.set("status", status);
  }
  const query = params.toString();
  return query ? `/urls?${query}` : "/urls";
}

export function MonitorsView({
  monitors,
  isAdmin,
  initialSearch,
  initialStatus,
}: MonitorsViewProps) {
  const router = useRouter();
  const [search, setSearch] = useState(initialSearch);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MonitorListItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MonitorListItem | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    setSearch(initialSearch);
  }, [initialSearch]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      const trimmed = search.trim();
      if (trimmed === initialSearch) {
        return;
      }
      startTransition(() => {
        router.push(buildUrl(trimmed, initialStatus));
      });
    }, 350);
    return () => window.clearTimeout(handle);
  }, [search, initialSearch, initialStatus, router]);

  function changeStatus(next: StatusFilter) {
    startTransition(() => {
      router.push(buildUrl(search.trim(), next));
    });
  }

  function openCreate() {
    setEditing(null);
    setModalOpen(true);
  }

  function openEdit(monitor: MonitorListItem) {
    setEditing(monitor);
    setModalOpen(true);
  }

  function refresh() {
    startTransition(() => {
      router.refresh();
    });
  }

  async function handleCheckNow(monitor: MonitorListItem) {
    setPendingId(monitor.id);
    setFeedback(null);
    try {
      const check = await checkMonitorNow(monitor.id);
      setFeedback({
        variant: check.status === "UP" ? "success" : "warning",
        title: `Check completed for ${monitor.name}`,
        body:
          check.status === "UP"
            ? `UP${check.response_time_ms !== null ? ` in ${check.response_time_ms} ms` : ""}.`
            : `DOWN${check.error_message ? `: ${check.error_message}` : "."}`,
      });
      refresh();
    } catch (caught) {
      setFeedback(feedbackFromError(caught));
    } finally {
      setPendingId(null);
    }
  }

  async function handleToggleActive(monitor: MonitorListItem) {
    setPendingId(monitor.id);
    setFeedback(null);
    try {
      const updated = await updateMonitor(monitor.id, { is_active: !monitor.is_active });
      setFeedback({
        variant: "success",
        title: updated.is_active ? "Monitor resumed" : "Monitor paused",
        body: `${updated.name} is now ${updated.is_active ? "active" : "paused"}.`,
      });
      refresh();
    } catch (caught) {
      setFeedback(feedbackFromError(caught));
    } finally {
      setPendingId(null);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) {
      return;
    }
    setPendingId(deleteTarget.id);
    setFeedback(null);
    try {
      await deleteMonitor(deleteTarget.id);
      setFeedback({
        variant: "success",
        title: "Monitor deleted",
        body: `${deleteTarget.name} and its check logs were removed.`,
      });
      setDeleteTarget(null);
      refresh();
    } catch (caught) {
      setFeedback(feedbackFromError(caught));
    } finally {
      setPendingId(null);
    }
  }

  const hasFilters = initialSearch.length > 0 || initialStatus !== "all";

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Monitored URLs</h2>
          <p className="text-sm text-muted-foreground">
            Search the directory, inspect status, and manage check configuration.
          </p>
        </div>
        {isAdmin ? (
          <Button type="button" onClick={openCreate}>
            <Plus aria-hidden="true" />
            Add URL
          </Button>
        ) : null}
      </div>

      {feedback ? (
        <Alert variant={feedback.variant}>
          <div>
            <AlertTitle>{feedback.title}</AlertTitle>
            <AlertDescription>{feedback.body}</AlertDescription>
          </div>
        </Alert>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by name or URL"
            className="pl-9"
            aria-label="Search monitors by name or URL"
          />
        </div>
        <div className="w-full sm:w-48">
          <Select
            value={initialStatus}
            onValueChange={(value) =>
              changeStatus(
                value === "up" || value === "down" || value === "paused" ? value : "all",
              )
            }
          >
            <SelectTrigger aria-label="Filter by status">
              <SelectValue placeholder="Filter status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="up">Up</SelectItem>
              <SelectItem value="down">Down</SelectItem>
              <SelectItem value="paused">Paused</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {isPending ? (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            Updating…
          </span>
        ) : null}
      </div>

      {monitors.length === 0 ? (
        <EmptyState
          title={hasFilters ? "No monitors match these filters" : "No monitors configured"}
          description={
            hasFilters
              ? "Try a different search term or clear the status filter."
              : isAdmin
                ? "Add the first URL to start recording availability and latency checks."
                : "An administrator has not added any URLs yet."
          }
          icon={<Search className="h-6 w-6" aria-hidden="true" />}
          action={
            hasFilters ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setSearch("");
                  startTransition(() => {
                    router.push("/urls");
                  });
                }}
              >
                Clear filters
              </Button>
            ) : isAdmin ? (
              <Button type="button" onClick={openCreate}>
                <Plus aria-hidden="true" />
                Add URL
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className={cn("rounded-xl border bg-white", isPending && "opacity-60")}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Status</TableHead>
                <TableHead>Name &amp; URL</TableHead>
                <TableHead>Method</TableHead>
                <TableHead>Interval</TableHead>
                <TableHead>Last latency</TableHead>
                <TableHead>Uptime (24h)</TableHead>
                <TableHead>SSL</TableHead>
                {isAdmin ? <TableHead className="text-right">Actions</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {monitors.map((monitor) => (
                <TableRow key={monitor.id}>
                  <TableCell>
                    <StatusBadge monitor={monitor} />
                  </TableCell>
                  <TableCell className="max-w-[22rem]">
                    <Link
                      href={`/urls/${monitor.id}`}
                      className="block truncate font-medium hover:underline"
                    >
                      {monitor.name}
                    </Link>
                    <a
                      href={monitor.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block truncate text-xs text-muted-foreground hover:underline"
                      title={monitor.url}
                    >
                      {monitor.url}
                    </a>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{monitor.http_method}</Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {formatInterval(monitor.interval_seconds)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {formatLatency(monitor.last_response_time_ms)}
                  </TableCell>
                  <TableCell>
                    <UptimeMeter value={monitor.uptime_24h} />
                  </TableCell>
                  <TableCell className={cn("whitespace-nowrap", sslTone(monitor.ssl_days_remaining))}>
                    {formatSslDays(monitor.ssl_days_remaining)}
                  </TableCell>
                  {isAdmin ? (
                    <TableCell className="text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={`Actions for ${monitor.name}`}
                            disabled={pendingId === monitor.id}
                          >
                            {pendingId === monitor.id ? (
                              <Loader2 className="animate-spin" aria-hidden="true" />
                            ) : (
                              <MoreHorizontal aria-hidden="true" />
                            )}
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-44">
                          <DropdownMenuItem onSelect={() => openEdit(monitor)}>
                            <Pencil className="h-4 w-4" aria-hidden="true" />
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => void handleCheckNow(monitor)}>
                            <RefreshCw className="h-4 w-4" aria-hidden="true" />
                            Check now
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => void handleToggleActive(monitor)}>
                            {monitor.is_active ? (
                              <>
                                <Pause className="h-4 w-4" aria-hidden="true" />
                                Pause
                              </>
                            ) : (
                              <>
                                <Play className="h-4 w-4" aria-hidden="true" />
                                Resume
                              </>
                            )}
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            className="text-red-600 focus:text-red-600"
                            onSelect={() => setDeleteTarget(monitor)}
                          >
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <MonitorFormModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        monitor={editing}
        onSaved={refresh}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
          }
        }}
        title="Delete monitor"
        description={
          deleteTarget
            ? `${deleteTarget.name} and all of its check logs and incidents will be permanently deleted.`
            : ""
        }
        confirmLabel="Delete monitor"
        pending={pendingId !== null && pendingId === deleteTarget?.id}
        onConfirm={() => void handleDelete()}
      />
    </div>
  );
}
