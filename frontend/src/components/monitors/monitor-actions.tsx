"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  Loader2,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { MonitorFormModal } from "@/components/monitors/monitor-form-modal";
import { ApiError, checkMonitorNow, deleteMonitor, updateMonitor } from "@/lib/api";
import type { MonitorDetail } from "@/types";

interface MonitorActionsProps {
  monitor: MonitorDetail;
}

interface Feedback {
  variant: "success" | "warning" | "destructive";
  title: string;
  body: string;
}

export function MonitorActions({ monitor }: MonitorActionsProps) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [pending, setPending] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [isPending, startTransition] = useTransition();

  function refresh() {
    startTransition(() => {
      router.refresh();
    });
  }

  async function handleCheckNow() {
    setPending(true);
    setFeedback(null);
    try {
      const check = await checkMonitorNow(monitor.id);
      setFeedback({
        variant: check.status === "UP" ? "success" : "warning",
        title: "Manual check completed",
        body:
          check.status === "UP"
            ? `UP${check.response_time_ms !== null ? ` in ${check.response_time_ms} ms` : ""}.`
            : `DOWN${check.error_message ? `: ${check.error_message}` : "."}`,
      });
      refresh();
    } catch (caught) {
      setFeedback({
        variant: "destructive",
        title: "Check failed",
        body: caught instanceof ApiError ? caught.message : "The manual check could not run.",
      });
    } finally {
      setPending(false);
    }
  }

  async function handleToggleActive() {
    setPending(true);
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
      setFeedback({
        variant: "destructive",
        title: "Update failed",
        body: caught instanceof ApiError ? caught.message : "The monitor could not be updated.",
      });
    } finally {
      setPending(false);
    }
  }

  async function handleDelete() {
    setPending(true);
    setFeedback(null);
    try {
      await deleteMonitor(monitor.id);
      setConfirmOpen(false);
      router.push("/urls");
      router.refresh();
    } catch (caught) {
      setFeedback({
        variant: "destructive",
        title: "Delete failed",
        body: caught instanceof ApiError ? caught.message : "The monitor could not be deleted.",
      });
      setConfirmOpen(false);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col items-stretch gap-2 sm:items-end">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={handleCheckNow} disabled={pending}>
          {pending ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw aria-hidden="true" />
          )}
          Check now
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleToggleActive}
          disabled={pending}
        >
          {monitor.is_active ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
          {monitor.is_active ? "Pause" : "Resume"}
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => setEditOpen(true)} disabled={pending}>
          <Pencil aria-hidden="true" />
          Edit
        </Button>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          onClick={() => setConfirmOpen(true)}
          disabled={pending}
        >
          <Trash2 aria-hidden="true" />
          Delete
        </Button>
      </div>

      {feedback ? (
        <div className="w-full sm:max-w-md">
          <Alert variant={feedback.variant}>
            <div>
              <AlertTitle>{feedback.title}</AlertTitle>
              <AlertDescription>{feedback.body}</AlertDescription>
            </div>
          </Alert>
        </div>
      ) : null}

      {isPending ? (
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          Refreshing…
        </span>
      ) : null}

      <MonitorFormModal
        open={editOpen}
        onOpenChange={setEditOpen}
        monitor={monitor}
        onSaved={refresh}
      />

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Delete monitor"
        description={`${monitor.name} and all of its check logs and incidents will be permanently deleted.`}
        confirmLabel="Delete monitor"
        pending={pending}
        onConfirm={() => void handleDelete()}
      />
    </div>
  );
}
