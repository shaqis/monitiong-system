"use client";

import { ErrorState } from "@/components/ui/error-state";

export default function UsersError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="py-8">
      <ErrorState
        title="The user list could not load"
        message={error.message || "The user list request failed."}
        onRetry={reset}
      />
    </div>
  );
}
