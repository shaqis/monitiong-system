"use client";

import { ErrorState } from "@/components/ui/error-state";

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-xl">
        <ErrorState
          title="Uptime Monitor is unavailable"
          message={error.message || "The application could not reach the backend."}
          onRetry={reset}
        />
      </div>
    </main>
  );
}
