"use client";

/**
 * Permission-aware UI primitives.
 *
 * These decide what a user is *offered*. They are not security — the server
 * enforces the same rules on every endpoint, and anything rendered here could
 * be revealed with devtools. The prototype must never claim otherwise (C4).
 *
 * Two deliberate behaviours:
 *
 *  - `PermissionGate` hides an action a user can never perform, so the screen
 *    is not full of dead buttons.
 *  - `PermissionButton` *shows* an action but disables it with a reason, for
 *    cases where hiding it would be confusing ("why can't I approve this?").
 */

import type { ReactNode } from "react";
import { Lock } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { usePermissions } from "@/hooks/use-session";
import type { PermissionCode } from "@/types";
import { cn } from "@/lib/utils";

export function PermissionGate({
  permission,
  anyOf,
  children,
  fallback = null,
}: {
  permission?: PermissionCode;
  anyOf?: PermissionCode[];
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { can, canAny } = usePermissions();
  const allowed = permission ? can(permission) : anyOf ? canAny(anyOf) : true;
  return <>{allowed ? children : fallback}</>;
}

/**
 * Same idea as `PermissionGate`, but gated on the Owner role rather than a
 * permission code — for the handful of actions (e.g. editing a product)
 * that should be offered to the Owner specifically, not to every role that
 * happens to hold the underlying permission.
 */
export function OwnerOnlyGate({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  const { isOwner } = usePermissions();
  return <>{isOwner ? children : fallback}</>;
}

export function PermissionButton({
  permission,
  deniedReason,
  disabled,
  children,
  className,
  ...props
}: {
  permission: PermissionCode;
  /** Shown in a tooltip when the permission is missing. */
  deniedReason?: string;
  } & React.ComponentProps<typeof Button>) {
  const { can, user } = usePermissions();
  const allowed = can(permission);

  if (allowed) {
    return (
      <Button disabled={disabled} className={className} {...props}>
        {children}
      </Button>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex">
          <Button disabled className={cn("pointer-events-none", className)} {...props}>
            <Lock className="size-3.5" />
            {children}
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {deniedReason ?? `Your role (${user?.roleName ?? "current role"}) cannot do this.`}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * Shown in place of a whole screen the user's role cannot open. The route is
 * still reachable — this is a signpost, not a barrier.
 */
export function NoAccess({ what = "this page" }: { what?: string }) {
  const { user } = usePermissions();
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <span className="flex size-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
        <Lock className="size-5" strokeWidth={1.8} />
      </span>
      <p className="mt-3.5 text-section text-foreground">You don&apos;t have access to {what}</p>
      <p className="mt-1 max-w-[420px] text-body text-muted-foreground">
        Your role is {user?.roleName ?? "not set"}. Ask an owner to grant the permission you need.
      </p>
    </div>
  );
}

/**
 * The standing note that role checks in this prototype are presentational.
 * Shown on the Roles and Users screens so nobody mistakes them for security.
 */
export function PermissionDisclaimer({ className }: { className?: string }) {
  return (
    <p className={cn("text-caption text-muted-foreground", className)}>
      Roles decide what this interface offers. The server checks the same permissions on every
      request — that check, not this one, is what actually protects your data.
    </p>
  );
}
