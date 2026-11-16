"use client";

import { ErrorState } from "@/components/ui/error-state";

export default function SettingsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="py-8">
      <ErrorState
        title="Email settings could not load"
        message={error.message || "The notification settings request failed."}
        onRetry={reset}
      />
    </div>
  );
}
