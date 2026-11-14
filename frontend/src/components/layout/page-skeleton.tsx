import { Skeleton } from "@/components/ui/skeleton";

export function PageSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading page">
      <div className="space-y-2">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-80" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <Skeleton key={item} className="h-28 w-full rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-72 w-full rounded-xl" />
      <div className="space-y-2">
        {[0, 1, 2, 3, 4].map((item) => (
          <Skeleton key={item} className="h-10 w-full" />
        ))}
      </div>
    </div>
  );
}
