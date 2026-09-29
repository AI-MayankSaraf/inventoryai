"use client";

import * as React from "react";
import { KeyRound, Lock, Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";

import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { PageHeader } from "@/components/common/page-header";
import { PermissionDisclaimer, PermissionGate } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateRole, useDeleteRole, useRoles, useUpdateRole } from "@/hooks/use-admin";
import { usePermissions, useSession } from "@/hooks/use-session";
import { PERMISSION_GROUPS, permissionLabel } from "@/lib/domain/permissions";
import { cn } from "@/lib/utils";
import type { PermissionCode, Role } from "@/types";

/**
 * Roles are lists of permission codes, read straight from the database.
 *
 * The seven built-ins stay read-only — their permission sets are what the
 * rest of the app is designed around — but a company can define roles of
 * its own beside them. Two rules shape what this screen offers:
 *
 *  * You cannot grant what you do not hold (BR-AUTH-09). The boxes for
 *    permissions the signed-in user lacks are disabled, with the reason
 *    said once rather than on every line.
 *  * You cannot edit the role you are signed in with — shrinking the role
 *    you are standing on is how a company locks itself out.
 */

type RoleRow = Role & { userCount: number };

const ALL_PERMISSION_COUNT = PERMISSION_GROUPS.reduce((n, g) => n + g.permissions.length, 0);

export function RolesScreen() {
  const rolesState = useRoles();
  const [selectedId, setSelectedId] = React.useState<string | undefined>(undefined);

  React.useEffect(() => {
    if (!selectedId && rolesState.data && rolesState.data.length > 0) {
      setSelectedId(rolesState.data[0].id);
    }
  }, [rolesState.data, selectedId]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Roles & Permissions"
        description="What each role is allowed to see and do across the app"
        actions={
          <PermissionGate permission="user.manage">
            <RoleDialog onSaved={() => rolesState.refresh()} />
          </PermissionGate>
        }
      />

      <Alert variant="info">
        <ShieldCheck />
        <AlertDescription>
          <PermissionDisclaimer />
        </AlertDescription>
      </Alert>

      <AsyncBoundary
        state={rolesState}
        isEmpty={(d) => d.length === 0}
        empty={{ icon: KeyRound, title: "No roles configured yet" }}
      >
        {(roles) => {
          const selected = roles.find((r) => r.id === selectedId) ?? roles[0];
          return (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
              <SectionCard title="Roles" className="lg:col-span-4" bodyClassName="p-0">
                <ul className="divide-y divide-border">
                  {roles.map((role) => (
                    <li key={role.id}>
                      <button
                        type="button"
                        data-testid={`role-${role.code}`}
                        onClick={() => setSelectedId(role.id)}
                        className={cn(
                          "flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors hover:bg-muted/50",
                          selected?.id === role.id && "bg-muted/70",
                        )}
                      >
                        <span className="flex items-center gap-2">
                          <span className="font-medium text-foreground">{role.name}</span>
                          {role.isSystem && <Badge variant="neutral">Built-in</Badge>}
                        </span>
                        <span className="text-caption text-muted-foreground">
                          {role.permissions.length} permission{role.permissions.length === 1 ? "" : "s"} ·{" "}
                          {role.userCount} user{role.userCount === 1 ? "" : "s"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </SectionCard>

              <div className="lg:col-span-8">
                {selected && (
                  <RoleDetail
                    role={selected}
                    onChanged={() => {
                      setSelectedId(undefined);
                      rolesState.refresh();
                    }}
                  />
                )}
              </div>
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}

function RoleDetail({ role, onChanged }: { role: RoleRow; onChanged: () => void }) {
  const assigned = React.useMemo(() => new Set(role.permissions), [role.permissions]);
  const { user } = useSession();
  const isOwnRole = user?.roleId === role.id;
  const remove = useDeleteRole(onChanged);

  // Anything the database grants that this app's own PERMISSION_GROUPS
  // doesn't list would otherwise render nowhere at all — a permission
  // silently missing from the matrix is exactly the kind of gap this screen
  // exists to close.
  const grouped = React.useMemo(() => new Set(PERMISSION_GROUPS.flatMap((g) => g.permissions)), []);
  const ungrouped = role.permissions.filter((code) => !grouped.has(code));

  return (
    <SectionCard
      title={role.name}
      description={role.description ?? undefined}
      action={
        <span className="flex items-center gap-2">
          <Badge variant="neutral">
            {role.permissions.length} of {ALL_PERMISSION_COUNT}
          </Badge>
          {!role.isSystem && !isOwnRole && (
            <PermissionGate permission="user.manage">
              <RoleDialog role={role} onSaved={onChanged} />
              <ConfirmButton
                variant="ghost"
                size="icon"
                className="size-8"
                tone="destructive"
                aria-label={`Delete ${role.name}`}
                title={`Delete ${role.name}?`}
                description={
                  role.userCount > 0
                    ? `${role.userCount} user(s) still have this role — move them to another role first.`
                    : "The role is removed. People who once held it keep their history."
                }
                confirmLabel="Delete role"
                disabled={role.userCount > 0}
                onConfirm={() => remove.run(role.id).then(() => undefined)}
              >
                <Trash2 className="size-3.5" />
              </ConfirmButton>
            </PermissionGate>
          )}
        </span>
      }
    >
      {role.isSystem ? (
        <Alert variant="default" className="m-4 mb-0">
          <Lock />
          <AlertDescription>
            {role.name} is a built-in role. Its permissions are fixed and shown here for reference —
            copy it if you need something close but different.
          </AlertDescription>
        </Alert>
      ) : isOwnRole ? (
        <Alert variant="warning" className="m-4 mb-0">
          <Lock />
          <AlertDescription>
            This is the role you are signed in with, so it cannot be edited from here — otherwise
            you could remove your own access halfway through.
          </AlertDescription>
        </Alert>
      ) : null}
      {remove.error && <FormError message={remove.error} className="m-4 mb-0" />}

      <div className="divide-y divide-border">
        {PERMISSION_GROUPS.map((group) => {
          const held = group.permissions.filter((code) => assigned.has(code)).length;
          return (
            <div key={group.label} className="px-4 py-3.5">
              <p className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
                {group.label}
                <span className="text-caption font-normal text-muted-foreground">
                  {held} of {group.permissions.length}
                </span>
              </p>
              <div className="mt-2.5 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
                {group.permissions.map((code) => (
                  <span
                    key={code}
                    className={cn(
                      "flex items-center gap-2 text-[13px]",
                      assigned.has(code) ? "text-foreground" : "text-muted-foreground/60",
                    )}
                  >
                    <Checkbox checked={assigned.has(code)} disabled aria-label={code} />
                    {permissionLabel(code)}
                  </span>
                ))}
              </div>
            </div>
          );
        })}

        {ungrouped.length > 0 && (
          <div className="px-4 py-3.5">
            <p className="text-[13px] font-semibold text-foreground">Other</p>
            <div className="mt-2.5 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
              {ungrouped.map((code) => (
                <span key={code} className="flex items-center gap-2 text-[13px] text-foreground">
                  <Checkbox checked disabled aria-label={code} />
                  {permissionLabel(code)}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </SectionCard>
  );
}

/**
 * Create a role, or edit one this company defined.
 *
 * The permission list is the same matrix the read-only view shows, with two
 * differences: the boxes are live, and anything the signed-in user does not
 * hold themselves is disabled — the server refuses those with
 * `ROLE_ESCALATION`, and a checkbox that cannot be saved is worse than one
 * that is visibly unavailable.
 */
function RoleDialog({ role, onSaved }: { role?: RoleRow; onSaved: () => void }) {
  const isEdit = !!role;
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [selected, setSelected] = React.useState<Set<PermissionCode>>(new Set());
  const { can } = usePermissions();

  const create = useCreateRole(() => {
    setOpen(false);
    onSaved();
  });
  const update = useUpdateRole(role?.id ?? "", () => {
    setOpen(false);
    onSaved();
  });
  const mutation = isEdit ? update : create;

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      setName(role?.name ?? "");
      setDescription(role?.description ?? "");
      setSelected(new Set((role?.permissions ?? []) as PermissionCode[]));
      create.reset();
      update.reset();
    }
  }

  function toggle(code: PermissionCode) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  const grantable = PERMISSION_GROUPS.flatMap((g) => g.permissions).filter((c) => can(c));
  const outOfReach = PERMISSION_GROUPS.flatMap((g) => g.permissions).length - grantable.length;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {isEdit ? (
          <Button variant="ghost" size="icon" className="size-8" aria-label={`Edit ${role!.name}`}>
            <Pencil className="size-3.5" />
          </Button>
        ) : (
          <Button data-testid="add-role">
            <Plus />
            New Role
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${role!.name}` : "Create a role"}</DialogTitle>
          <DialogDescription>
            Pick what this role may do. Everyone holding it is signed out when you save, so their
            next sign-in picks up the change.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="role-name">Role name</Label>
              <Input
                id="role-name"
                value={name}
                placeholder="e.g. Store Supervisor"
                onChange={(e) => setName(e.target.value)}
                aria-invalid={!!mutation.fieldErrors.name}
                autoFocus
              />
              {mutation.fieldErrors.name && (
                <p className="text-caption text-destructive">{mutation.fieldErrors.name}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="role-description">Description (optional)</Label>
              <Input
                id="role-description"
                value={description}
                placeholder="What this role is for"
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </div>

          {outOfReach > 0 && (
            <p className="text-caption text-muted-foreground">
              {outOfReach} permission{outOfReach === 1 ? " is" : "s are"} greyed out because your own
              role doesn&apos;t hold {outOfReach === 1 ? "it" : "them"} — a role can never grant more
              than the person creating it has.
            </p>
          )}

          <div className="max-h-[42vh] divide-y divide-border overflow-y-auto rounded-lg border border-border">
            {PERMISSION_GROUPS.map((group) => (
              <div key={group.label} className="px-3.5 py-3">
                <p className="text-[13px] font-semibold text-foreground">{group.label}</p>
                <div className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
                  {group.permissions.map((code) => {
                    const allowed = can(code);
                    return (
                      <label
                        key={code}
                        className={cn(
                          "flex items-center gap-2 text-[13px]",
                          allowed ? "text-foreground" : "text-muted-foreground/60",
                        )}
                      >
                        <Checkbox
                          checked={selected.has(code)}
                          disabled={!allowed}
                          aria-label={code}
                          onCheckedChange={() => toggle(code)}
                        />
                        {permissionLabel(code)}
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          <p className="text-caption text-muted-foreground">
            {selected.size} permission{selected.size === 1 ? "" : "s"} selected
          </p>
        </DialogBody>

        <FormError message={mutation.error} fieldErrors={mutation.fieldErrors} />

        <DialogFooter>
          <Button
            disabled={mutation.isPending || !name.trim()}
            onClick={() => {
              const permissions = [...selected];
              if (isEdit) void update.run({ name, description, permissions });
              else void create.run({ name, description, permissions });
            }}
          >
            {mutation.isPending ? "Saving..." : isEdit ? "Save Role" : "Create Role"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
