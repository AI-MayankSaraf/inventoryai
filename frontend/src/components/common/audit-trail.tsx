"use client";

import * as React from "react";
import { History, Plus, Trash2, UserCircle } from "lucide-react";

import { AsyncBoundary, LoadingCard } from "@/components/common/async-state";
import { SectionCard } from "@/components/common/section-card";
import { Badge } from "@/components/ui/badge";
import { useAuditTrail } from "@/hooks/use-ops";
import { formatDateTime, formatRelativeTime } from "@/lib/format";
import type { AuditLog } from "@/types";

/**
 * "Who did what, when" for a single record.
 *
 * The trail is read through the API like everything else, and it is written by
 * the API — every mutating call records an entry, so the panel cannot go out
 * of step with what actually happened. Entries include the before/after values
 * for the fields that changed.
 */

function actionTone(action: string): React.ComponentProps<typeof Badge>["variant"] {
  if (/delete|removed|reject|dispute/.test(action)) return "destructive";
  if (/approve|accept|confirm|reactivat|matched/.test(action)) return "success";
  if (/sent|resent|invit|impersonat/.test(action)) return "info";
  if (/suspend|revok|reversed|cancel/.test(action)) return "warning";
  return "neutral";
}

function actionIcon(action: string) {
  if (/delete|removed/.test(action)) return Trash2;
  if (/created|invited/.test(action)) return Plus;
  return History;
}

function actionLabel(action: string): string {
  return action.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function AuditEventList({
  events,
  emptyLabel = "No activity recorded yet.",
  showEntity = false,
}: {
  events: AuditLog[];
  emptyLabel?: string;
  showEntity?: boolean;
}) {
  if (events.length === 0) {
    return (
      <div className="flex items-center gap-2.5 px-4 py-6 text-[13px] text-muted-foreground">
        <History className="size-4 shrink-0" />
        {emptyLabel}
      </div>
    );
  }

  return (
    <ul className="divide-y divide-border">
      {events.map((event) => {
        const Icon = actionIcon(event.action);
        return (
          <li key={event.id} className="flex items-start gap-3 px-4 py-3">
            <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Icon className="size-3.5" strokeWidth={2} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={actionTone(event.action)}>{actionLabel(event.action)}</Badge>
                {showEntity && (
                  <span className="text-[12.5px] font-medium text-foreground">{event.entityLabel}</span>
                )}
                {event.description && (
                  <span className="text-[12.5px] text-muted-foreground">{event.description}</span>
                )}
              </div>

              {event.changedFields?.length ? (
                <ul className="mt-1.5 space-y-0.5">
                  {event.changedFields.map((field) => (
                    <li key={field} className="text-caption text-muted-foreground">
                      <span className="font-medium text-foreground/75">{field}</span>:{" "}
                      <span className="line-through">{renderValue(event.beforeData?.[field])}</span>{" "}
                      → <span className="text-foreground/85">{renderValue(event.afterData?.[field])}</span>
                    </li>
                  ))}
                </ul>
              ) : null}

              <p className="mt-1 flex flex-wrap items-center gap-1.5 text-caption text-muted-foreground">
                <UserCircle className="size-3.5 shrink-0" />
                <span className="font-medium text-foreground/80">{event.actorName}</span>
                {event.actorRole && <span>· {event.actorRole}</span>}
                {event.impersonatedBy && (
                  <Badge variant="warning" className="ml-0.5">
                    via impersonation
                  </Badge>
                )}
                <span className="text-border">·</span>
                <span title={formatDateTime(event.createdAt)}>{formatRelativeTime(event.createdAt)}</span>
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function AuditTrail({
  entityType,
  entityId,
  title = "Audit trail",
  className,
}: {
  entityType: string;
  entityId: string;
  title?: string;
  className?: string;
}) {
  const state = useAuditTrail(entityType, entityId);

  return (
    <SectionCard
      title={title}
      description={state.data?.length ? `${state.data.length} event${state.data.length === 1 ? "" : "s"}` : undefined}
      className={className}
    >
      <AsyncBoundary state={state} loading={<LoadingCard />}>
        {(events) => (
          <AuditEventList events={events} emptyLabel="No activity recorded for this record yet." />
        )}
      </AsyncBoundary>
    </SectionCard>
  );
}
