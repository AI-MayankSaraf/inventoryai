"use client";

/**
 * Loading, error and empty handling for data-backed screens.
 *
 * Every screen now reads from an async source, so every screen needs the same
 * three states. Doing it once here keeps them consistent and stops components
 * rendering `undefined.map(...)` on the first paint.
 */

import type { ReactNode } from "react";
import { AlertTriangle, type LucideIcon } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function LoadingRows({ rows = 5, columns = 5 }: { rows?: number; columns?: number }) {
  return (
    <div className="divide-y divide-border" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex items-center gap-4 px-4 py-3">
          {Array.from({ length: columns }).map((_, colIndex) => (
            <Skeleton
              key={colIndex}
              className={cn("h-4", colIndex === 0 ? "w-[22%]" : "flex-1")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function LoadingCard({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-3 p-4", className)} aria-busy="true" aria-label="Loading">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  className,
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      <span className="flex size-11 items-center justify-center rounded-xl bg-destructive-subtle text-destructive-subtle-foreground">
        <AlertTriangle className="size-5" strokeWidth={1.8} />
      </span>
      <p className="mt-3.5 text-section text-foreground">That didn&apos;t work</p>
      <p className="mt-1 max-w-[420px] text-body text-muted-foreground">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export interface AsyncBoundaryProps<T> {
  state: { data: T | undefined; error: string | null; isLoading: boolean; refresh: () => void };
  /** Rendered when the query succeeds. */
  children: (data: T) => ReactNode;
  loading?: ReactNode;
  /** Treat this data as empty — renders `empty` instead of `children`. */
  isEmpty?: (data: T) => boolean;
  empty?: { icon: LucideIcon; title: string; description?: string; action?: ReactNode };
}

/** One place that decides which of loading / error / empty / content to show. */
export function AsyncBoundary<T>({
  state,
  children,
  loading,
  isEmpty,
  empty,
}: AsyncBoundaryProps<T>) {
  if (state.isLoading && state.data === undefined) {
    return <>{loading ?? <LoadingRows />}</>;
  }
  if (state.error) {
    return <ErrorState message={state.error} onRetry={state.refresh} />;
  }
  if (state.data === undefined) {
    return <>{loading ?? <LoadingRows />}</>;
  }
  if (empty && isEmpty?.(state.data)) {
    return (
      <EmptyState
        icon={empty.icon}
        title={empty.title}
        description={empty.description}
        action={empty.action}
      />
    );
  }
  return <>{children(state.data)}</>;
}

/** Inline error strip for a form, with the failing fields listed. */
export function FormError({
  message,
  fieldErrors,
  className,
}: {
  message: string | null;
  fieldErrors?: Record<string, string>;
  className?: string;
}) {
  if (!message) return null;
  const fields = Object.entries(fieldErrors ?? {});
  return (
    <div
      role="alert"
      className={cn(
        "rounded-lg border border-destructive/30 bg-destructive-subtle px-3 py-2.5 text-body text-destructive-subtle-foreground",
        className,
      )}
    >
      <p className="font-medium">{message}</p>
      {fields.length > 0 && (
        <ul className="mt-1.5 list-disc space-y-0.5 pl-4">
          {fields.map(([field, error]) => (
            <li key={field}>{error}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
