"use client";

import { ErrorState } from "@/components/ui/error-state";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="py-8">
      <ErrorState
        title="The dashboard could not load"
        message={error.message || "The dashboard summary request failed."}
        onRetry={reset}
      />
    </div>
  );
}
