import { cn } from "@/lib/utils";

interface UptimeMeterProps {
  value: number | null | undefined;
}

export function UptimeMeter({ value }: UptimeMeterProps) {
  if (value === null || value === undefined) {
    return <span className="text-sm text-muted-foreground">—</span>;
  }

  const width = Math.min(100, Math.max(0, value));
  const tone =
    value >= 99.5 ? "bg-emerald-500" : value >= 95 ? "bg-amber-500" : "bg-red-500";
  const textTone =
    value >= 99.5 ? "text-emerald-600" : value >= 95 ? "text-amber-600" : "text-red-600";

  return (
    <div className="min-w-[5rem] space-y-1">
      <span className={cn("text-sm font-medium", textTone)}>{value.toFixed(2)}%</span>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}
