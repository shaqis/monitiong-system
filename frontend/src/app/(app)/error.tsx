"use client";

import { ErrorState } from "@/components/ui/error-state";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="py-8">
      <ErrorState
        title="The page could not load"
        message={error.message || "The server returned an unexpected response."}
        onRetry={reset}
      />
    </div>
  );
}
