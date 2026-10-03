"use client";

/**
 * The feature-hook layer.
 *
 * Components never call the API directly and never hold a promise: they call a
 * hook, and get `{ data, error, isLoading, refresh }`. This is the layer that
 * makes the app behave correctly around asynchronous data — loading states,
 * caching, dedup, refetch after a mutation.
 *
 * `useApiQuery` is a thin wrapper over TanStack Query. Every call site must
 * pass a `QueryKey` array whose first element uniquely identifies *what* is
 * being fetched (e.g. `["brands"]`, `["product", productVariantId]`) —
 * TanStack Query caches by this key, not by the fetcher function, so two
 * different endpoints must never share a key or they will read each other's
 * cached data.
 *
 * `staleTime` (set globally in `src/app/providers.tsx`) is what actually
 * fixes the "every page flashes a spinner" symptom: revisiting a screen
 * within the stale window serves the cached list instantly instead of
 * re-fetching and re-rendering empty state first.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { errorMessage } from "@/lib/api";

export interface QueryState<T> {
  data: T | undefined;
  error: string | null;
  isLoading: boolean;
  /** True while refetching data that is already on screen. */
  isRefreshing: boolean;
  refresh: () => void;
}

export interface QueryOptions<T = unknown> {
  /** Skip the request entirely — for dependent queries. */
  enabled?: boolean;
  /**
   * Ask again every N ms while the returned value is a number — e.g. while a
   * document is still being read. Given the latest data; `false` stops.
   */
  pollWhile?: (data: T | undefined) => number | false;
}

export function useApiQuery<T>(
  key: QueryKey,
  fetcher: () => Promise<T>,
  options: QueryOptions<T> = {},
): QueryState<T> {
  const { enabled = true, pollWhile } = options;
  const queryClient = useQueryClient();
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const keySignature = JSON.stringify(key);

  const query = useQuery<T>({
    queryKey: key,
    queryFn: () => fetcherRef.current(),
    enabled,
    refetchInterval: pollWhile ? (q) => pollWhile(q.state.data) : undefined,
  });

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: key });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryClient, keySignature]);

  return {
    data: query.data,
    error: query.error ? errorMessage(query.error) : null,
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    refresh,
  };
}

export interface MutationState<TInput, TResult> {
  run: (input: TInput) => Promise<TResult | undefined>;
  isPending: boolean;
  error: string | null;
  fieldErrors: Record<string, string>;
  reset: () => void;
  data: TResult | undefined;
}

export interface MutationOptions<TResult> {
  onSuccess?: (result: TResult) => void;
  onError?: (message: string) => void;
}

/**
 * A mutation with the field-level errors the API returns already unpacked, so
 * a form can show them next to the inputs that caused them.
 */
export function useApiMutation<TInput, TResult>(
  action: (input: TInput) => Promise<TResult>,
  options: MutationOptions<TResult> = {},
): MutationState<TInput, TResult> {
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [data, setData] = useState<TResult | undefined>(undefined);
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const actionRef = useRef(action);
  actionRef.current = action;
  const queryClient = useQueryClient();

  const run = useCallback(async (input: TInput) => {
    setIsPending(true);
    setError(null);
    setFieldErrors({});
    try {
      const result = await actionRef.current(input);
      setData(result);
      // Every write the API accepts records an audit event, so any Audit
      // Trail panel on screen is now behind. Without this the panel kept
      // its cached copy — adding a supplier to an RFQ left it showing only
      // "Created" until the page was reloaded.
      void queryClient.invalidateQueries({ queryKey: ["audit-trail"] });
      optionsRef.current.onSuccess?.(result);
      return result;
    } catch (err) {
      const message = errorMessage(err);
      setError(message);
      const fields = (err as { fieldErrors?: { field: string; message: string }[] })?.fieldErrors;
      if (fields?.length) {
        setFieldErrors(Object.fromEntries(fields.map((f) => [f.field, f.message])));
      }
      optionsRef.current.onError?.(message);
      return undefined;
    } finally {
      setIsPending(false);
    }
  }, [queryClient]);

  const reset = useCallback(() => {
    setError(null);
    setFieldErrors({});
    setData(undefined);
  }, []);

  return { run, isPending, error, fieldErrors, reset, data };
}

/** Debounced value, for search boxes that drive a `ListParams.q`. */
export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(handle);
  }, [value, delay]);
  return debounced;
}

/**
 * List-screen state: search, filters, sort and paging, packaged as the
 * `ListParams` every collection endpoint accepts. Screens stop filtering
 * arrays in render and start describing the query they want.
 */
export interface ListControls {
  q: string;
  setQ: (value: string) => void;
  filters: Record<string, string | undefined>;
  setFilter: (key: string, value: string | undefined) => void;
  clearFilters: () => void;
  sort: string | undefined;
  setSort: (value: string | undefined) => void;
  dateFrom?: string;
  dateTo?: string;
  setDateRange: (from?: string, to?: string) => void;
  params: {
    q?: string;
    filters: Record<string, string | undefined>;
    sort?: string;
    dateFrom?: string;
    dateTo?: string;
    limit?: number;
  };
  activeFilterCount: number;
}

export function useListControls(initial: {
  filters?: Record<string, string | undefined>;
  sort?: string;
  limit?: number;
} = {}): ListControls {
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<Record<string, string | undefined>>(initial.filters ?? {});
  const [sort, setSort] = useState<string | undefined>(initial.sort);
  const [dateFrom, setDateFrom] = useState<string | undefined>(undefined);
  const [dateTo, setDateTo] = useState<string | undefined>(undefined);
  const debouncedQ = useDebounced(q);

  const setFilter = useCallback((key: string, value: string | undefined) => {
    setFilters((current) => {
      const next = { ...current };
      if (!value || value === "all") delete next[key];
      else next[key] = value;
      return next;
    });
  }, []);

  const clearFilters = useCallback(() => {
    setFilters({});
    setQ("");
    setDateFrom(undefined);
    setDateTo(undefined);
  }, []);

  const setDateRange = useCallback((from?: string, to?: string) => {
    setDateFrom(from);
    setDateTo(to);
  }, []);

  const params = useMemo(
    () => ({
      q: debouncedQ || undefined,
      filters,
      sort,
      dateFrom,
      dateTo,
      limit: initial.limit,
    }),
    [debouncedQ, filters, sort, dateFrom, dateTo, initial.limit],
  );

  const activeFilterCount =
    Object.values(filters).filter(Boolean).length + (dateFrom || dateTo ? 1 : 0);

  return {
    q,
    setQ,
    filters,
    setFilter,
    clearFilters,
    sort,
    setSort,
    dateFrom,
    dateTo,
    setDateRange,
    params,
    activeFilterCount,
  };
}
