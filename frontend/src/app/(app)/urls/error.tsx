"use client";

import { ErrorState } from "@/components/ui/error-state";

export default function UrlsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="py-8">
      <ErrorState
        title="The URL list could not load"
        message={error.message || "The monitor list request failed."}
        onRetry={reset}
      />
    </div>
  );
}
