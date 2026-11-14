"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { cn } from "@/lib/utils";
import type { TimeRange } from "@/types";

const RANGES: Array<{ value: TimeRange; label: string }> = [
  { value: "1h", label: "1H" },
  { value: "24h", label: "24H" },
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
];

interface RangeSelectorProps {
  value: TimeRange;
}

export function RangeSelector({ value }: RangeSelectorProps) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function select(next: TimeRange) {
    if (next === value) {
      return;
    }
    startTransition(() => {
      router.push(`/dashboard?range=${next}`);
    });
  }

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-md border bg-white p-1 shadow-sm",
        pending && "opacity-70",
      )}
      role="group"
      aria-label="Dashboard time range"
    >
      {RANGES.map((range) => (
        <button
          key={range.value}
          type="button"
          onClick={() => select(range.value)}
          aria-pressed={value === range.value}
          disabled={pending}
          className={cn(
            "rounded px-3 py-1.5 text-xs font-semibold transition-colors",
            value === range.value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          {range.label}
        </button>
      ))}
    </div>
  );
}
