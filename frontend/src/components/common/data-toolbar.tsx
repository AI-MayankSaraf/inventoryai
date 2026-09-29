import * as React from "react";
import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

/** Search + filters row that sits directly above a table. */
export function DataToolbar({
  searchPlaceholder = "Search...",
  searchValue,
  onSearchChange,
  filters,
  trailing,
  className,
}: {
  searchPlaceholder?: string;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  filters?: React.ReactNode;
  trailing?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2.5 border-b border-border px-4 py-3 lg:flex-row lg:items-center",
        className,
      )}
    >
      <div className="relative w-full lg:max-w-[300px]">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          type="search"
          placeholder={searchPlaceholder}
          value={searchValue}
          onChange={onSearchChange ? (e) => onSearchChange(e.target.value) : undefined}
          className="h-9 w-full rounded-md border border-input bg-card pr-3 pl-9 text-[13.5px] outline-none placeholder:text-muted-foreground/80 focus:border-ring focus:ring-[3px] focus:ring-ring/20 [&::-webkit-search-cancel-button]:hidden"
        />
      </div>
      {filters && (
        <div className="flex flex-wrap items-center gap-2 lg:flex-nowrap">{filters}</div>
      )}
      {trailing && <div className="flex items-center gap-2 lg:ml-auto">{trailing}</div>}
    </div>
  );
}

/** Table footer with result count and page controls. */
export function TablePagination({
  page = 1,
  pageSize = 10,
  total,
  onPageChange,
  className,
}: {
  page?: number;
  pageSize?: number;
  total: number;
  onPageChange?: (page: number) => void;
  className?: string;
}) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-between gap-2 border-t border-border px-4 py-2.5 sm:flex-row",
        className,
      )}
    >
      <p className="text-caption text-muted-foreground">
        Showing <span className="font-medium text-foreground tabular">{from}–{to}</span> of{" "}
        <span className="font-medium text-foreground tabular">{total}</span>
      </p>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onPageChange?.(page - 1)}
          className="rounded-md border border-border px-2.5 py-1 text-[12.5px] font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-45"
        >
          Previous
        </button>
        <span className="px-2 text-caption text-muted-foreground tabular">
          Page {page} of {pages}
        </span>
        <button
          type="button"
          disabled={page >= pages}
          onClick={() => onPageChange?.(page + 1)}
          className="rounded-md border border-border px-2.5 py-1 text-[12.5px] font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-45"
        >
          Next
        </button>
      </div>
    </div>
  );
}
