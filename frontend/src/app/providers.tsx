"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * One QueryClient per browser tab, created lazily so it survives Fast
 * Refresh without losing its cache and is never shared across requests on
 * the server (there is no server-side data fetching through this client —
 * every screen fetches from the browser — but a fresh client per render
 * would still defeat the whole point of caching).
 *
 * `staleTime` is deliberately not 0: master/list data here does not change
 * on its own, so a screen you already visited should render instantly from
 * cache while a background refetch (if any) happens silently, instead of
 * showing a loading spinner again for data you just had on screen.
 */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: false,
        refetchOnWindowFocus: false,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

function getQueryClient() {
  if (typeof window === "undefined") return makeQueryClient();
  if (!browserQueryClient) browserQueryClient = makeQueryClient();
  return browserQueryClient;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const client = getQueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
