/**
 * Audit trail writer.
 *
 * Every mutating API call records what changed, who did it and when. In the
 * real system this is a database trigger plus an application-level actor, so
 * it cannot be skipped; here it is one helper that every write goes through,
 * which is the same guarantee at this layer.
 */

import { insert } from "@/mock/repository";
import type { AuditAction, AuditLog, Id } from "@/types";
import { currentImpersonation, currentSession } from "./auth.api";

let counter = 0;

export interface AuditInput {
  entityType: string;
  entityId: Id;
  entityLabel: string;
  action: AuditAction;
  description?: string;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
}

export function recordAudit(input: AuditInput): AuditLog {
  const session = currentSession();
  const impersonation = currentImpersonation();
  counter += 1;
  const entry: AuditLog = {
    id: `aud_${Date.now().toString(36)}${counter.toString(36)}`,
    entityType: input.entityType,
    entityId: input.entityId,
    entityLabel: input.entityLabel,
    action: input.action,
    description: input.description,
    actorUserId: session?.id ?? null,
    actorName: session?.fullName ?? "System",
    actorRole: session?.roleName,
    impersonatedBy: impersonation ? impersonation.platformUserId : null,
    beforeData: input.before ?? null,
    afterData: input.after ?? null,
    changedFields: diffKeys(input.before, input.after),
    createdAt: new Date().toISOString(),
  };
  insert("auditLogs", entry);
  return entry;
}

function diffKeys(
  before: Record<string, unknown> | null | undefined,
  after: Record<string, unknown> | null | undefined,
): string[] | undefined {
  if (!before || !after) return undefined;
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  const changed = [...keys].filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]));
  return changed.length ? changed : undefined;
}

/** The id of whoever is acting, for `performedBy` style columns. */
export function actorId(): Id {
  return currentSession()?.id ?? "usr_system";
}

export function actorName(): string {
  return currentSession()?.fullName ?? "System";
}
