"use client";

import * as React from "react";
import { History } from "lucide-react";

import { AsyncBoundary } from "@/components/common/async-state";
import { AuditEventList } from "@/components/common/audit-trail";
import { DataToolbar, TablePagination } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { PageHeader } from "@/components/common/page-header";
import { Card } from "@/components/ui/card";
import { useListControls } from "@/hooks/use-api";
import { useAuditLogs } from "@/hooks/use-ops";

/**
 * "Who did what, when" across the whole company.
 *
 * The backend writes an entry for every change it makes, so this list
 * is the record itself, not a summary of one — the same trail a detail
 * screen's audit panel reads from, just company-wide and filterable.
 */

function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function AuditLogScreen() {
  const controls = useListControls({ sort: "-createdAt" });
  const state = useAuditLogs(controls.params);

  // A large, unfiltered read purely to build the filter option lists from
  // real recorded values — never a hardcoded list of actions or entity types.
  const optionsState = useAuditLogs({ limit: 1000 });
  const optionRows = React.useMemo(() => optionsState.data?.items ?? [], [optionsState.data]);

  const actionOptions = React.useMemo(() => {
    const map: Record<string, string> = {};
    for (const row of optionRows) map[titleCase(row.action)] = row.action;
    return map;
  }, [optionRows]);

  const entityTypeOptions = React.useMemo(() => {
    const map: Record<string, string> = {};
    for (const row of optionRows) map[titleCase(row.entityType)] = row.entityType;
    return map;
  }, [optionRows]);

  const actorOptions = React.useMemo(
    () => Array.from(new Set(optionRows.map((row) => row.actorName))).sort(),
    [optionRows],
  );

  const labelFor = (map: Record<string, string>, value?: string) =>
    Object.keys(map).find((key) => map[key] === value);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Audit Trail"
        description="Every create, edit, status change and delete recorded across your company"
      />

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search by record, actor or description..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <>
              <FilterSelect
                placeholder="All Actions"
                options={Object.keys(actionOptions)}
                className="w-[160px]"
                value={labelFor(actionOptions, controls.filters.action)}
                onValueChange={(v) => controls.setFilter("action", v ? actionOptions[v] : undefined)}
              />
              <FilterSelect
                placeholder="All Record Types"
                options={Object.keys(entityTypeOptions)}
                className="w-[172px]"
                value={labelFor(entityTypeOptions, controls.filters.entityType)}
                onValueChange={(v) =>
                  controls.setFilter("entityType", v ? entityTypeOptions[v] : undefined)
                }
              />
              <FilterSelect
                placeholder="All Actors"
                options={actorOptions}
                className="w-[168px]"
                value={controls.filters.actorName}
                onValueChange={(v) => controls.setFilter("actorName", v)}
              />
            </>
          }
        />

        <AsyncBoundary
          state={state}
          isEmpty={(d) => d.items.length === 0}
          empty={{
            icon: History,
            title: controls.activeFilterCount || controls.q ? "No activity matches your filters" : "No activity recorded yet",
          }}
        >
          {(data) => (
            <>
              <AuditEventList events={data.items} showEntity />
              <TablePagination page={1} pageSize={Math.max(data.items.length, 1)} total={data.total} />
            </>
          )}
        </AsyncBoundary>
      </Card>
    </div>
  );
}
