"use client";

import { ErrorState } from "@/components/ui/error-state";

export default function MonitorDetailError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="py-8">
      <ErrorState
        title="The monitor could not load"
        message={error.message || "The monitor detail request failed."}
        onRetry={reset}
      />
    </div>
  );
}
