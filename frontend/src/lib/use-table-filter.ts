"use client";

import * as React from "react";

export type FilterDef<T> = {
  /** Key used in the internal filter-value map. */
  key: string;
  /** Pulls the comparable string value off a row for this filter. */
  accessor: (row: T) => string;
};

/**
 * Client-side search + filter-dropdown state for a table. Give it the full
 * dataset, a function that returns the searchable text for a row, and a list
 * of dropdown filters (each keyed to an accessor) — it returns the filtered
 * rows plus everything needed to wire up `DataToolbar` / `FilterSelect`.
 */
export function useTableFilter<T>(
  data: T[],
  searchKeys: (row: T) => string[],
  filterDefs: FilterDef<T>[] = [],
) {
  const [search, setSearch] = React.useState("");
  const [filterValues, setFilterValues] = React.useState<Record<string, string>>({});

  const setFilter = React.useCallback((key: string, value: string) => {
    setFilterValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    return data.filter((row) => {
      if (q && !searchKeys(row).some((s) => s?.toLowerCase().includes(q))) {
        return false;
      }
      for (const def of filterDefs) {
        const active = filterValues[def.key];
        if (active && active !== "all" && def.accessor(row) !== active) {
          return false;
        }
      }
      return true;
    });
  }, [data, search, filterValues, searchKeys, filterDefs]);

  return { filtered, search, setSearch, filterValues, setFilter };
}
