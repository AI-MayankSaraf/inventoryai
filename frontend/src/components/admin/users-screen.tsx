"use client";

import * as React from "react";
import { ExternalLink, Pencil, Plus, RotateCw, Send, Trash2, Users2 } from "lucide-react";

import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { DataToolbar } from "@/components/common/data-toolbar";
import { FilterSelect } from "@/components/common/filter-select";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { PageHeader } from "@/components/common/page-header";
import { PermissionDisclaimer, PermissionGate } from "@/components/common/permission-gate";
import { StatusBadge } from "@/components/common/status-badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useListControls } from "@/hooks/use-api";
import {
  useGodownsWithUsage,
  useInvitations,
  useInviteUser,
  useRemoveUser,
  useResendInvitation,
  useRevokeInvitation,
  useRoles,
  useUpdateUserAccess,
  useUsers,
} from "@/hooks/use-admin";
import { formatDate, formatRelativeTime } from "@/lib/format";
import type { Godown, GodownScope, Invitation, Role, User, UserStatus } from "@/types";

/**
 * Who can sign in, and what they are allowed to do.
 *
 * Roles and godown scope are chosen from the same data the rest of the app
 * reads (`useRoles`, `useGodownsWithUsage`) — never a hardcoded list. The API
 * refuses to demote or deactivate the last active owner (BR-AUTH-04) and caps
 * invitation resends at five (BR-AUTH-07); this screen does not re-derive
 * those rules, it just shows the message the API sends back.
 */

type GodownRow = Godown & { skuCount: number; stockValue: number };
type RoleRow = Role & { userCount: number };

const STATUS_VALUES: Record<string, UserStatus> = {
  Active: "active",
  Inactive: "inactive",
  Invited: "invited",
  Suspended: "suspended",
};

function initials(name: string) {
  return name
    .split(" ")
    .map((p) => p[0])
    .filter(Boolean)
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function UsersScreen() {
  const controls = useListControls({ sort: "fullName" });
  const usersState = useUsers(controls.params);
  const invitationsState = useInvitations();
  const rolesState = useRoles();
  const godownsState = useGodownsWithUsage();

  const roles = rolesState.data ?? [];
  const godowns = godownsState.data ?? [];

  // Every mutation on this screen changes a list on it, and none of those
  // lists refresh by themselves, so each write names what it invalidates.
  // Role user counts move with the user list, so a user change refreshes the
  // roles too.
  const refreshInvitations = invitationsState.refresh;
  const refreshUserList = usersState.refresh;
  const refreshRoles = rolesState.refresh;
  const refreshUsers = React.useCallback(() => {
    refreshUserList();
    refreshRoles();
  }, [refreshUserList, refreshRoles]);

  // The newest accept link from an invite or resend (development only).
  const [latestInvite, setLatestInvite] = React.useState<Invitation | null>(null);
  const onInvited = React.useCallback(
    (inv?: Invitation) => {
      refreshInvitations();
      setLatestInvite(inv?.inviteLink ? inv : null);
    },
    [refreshInvitations],
  );
  const resend = useResendInvitation(onInvited);
  const revoke = useRevokeInvitation(refreshInvitations);
  const removeUser = useRemoveUser(refreshUsers);

  const [manageUser, setManageUser] = React.useState<User | null>(null);

  const labelForStatus = (value?: string) =>
    Object.keys(STATUS_VALUES).find((key) => STATUS_VALUES[key] === value);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Users"
        description="Who can sign in, and what they are allowed to do"
        actions={
          <PermissionGate permission="user.manage">
            <InviteUserDialog roles={roles} godowns={godowns} onInvited={onInvited} />
          </PermissionGate>
        }
      />

      <PermissionDisclaimer />

      {invitationsState.data && invitationsState.data.length > 0 && (
        <Card className="overflow-hidden">
          <div className="border-b border-border px-4 py-3">
            <h3 className="text-[14px] font-semibold text-foreground">
              Pending Invitations
              <span className="ml-2 font-normal text-muted-foreground">
                ({invitationsState.data.length})
              </span>
            </h3>
            <p className="text-caption text-muted-foreground">
              Not yet accepted. Once someone accepts, they move into the user list below.
            </p>
          </div>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Invitee</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Invited On</TableHead>
                <TableHead>Invited By</TableHead>
                <PermissionGate permission="user.manage">
                  <TableHead className="pr-4 text-right">Actions</TableHead>
                </PermissionGate>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invitationsState.data.map((inv) => (
                <TableRow key={inv.id}>
                  <TableCell className="pl-4">
                    <span className="block font-medium text-foreground">{inv.fullName}</span>
                    <span className="block text-caption text-muted-foreground">{inv.email}</span>
                  </TableCell>
                  <TableCell>
                    <Badge variant="neutral">{roles.find((r) => r.id === inv.roleId)?.name ?? inv.roleCode}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(inv.invitedAt)}
                    {inv.resendCount > 0 && (
                      <span className="ml-1.5 text-caption">(resent {inv.resendCount}x)</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{inv.invitedByName}</TableCell>
                  <PermissionGate permission="user.manage">
                    <TableCell className="pr-4">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={resend.isPending}
                          onClick={() => resend.run(inv.id)}
                        >
                          <RotateCw />
                          Resend
                        </Button>
                        <ConfirmButton
                          variant="ghost"
                          size="icon-sm"
                          tone="destructive"
                          title="Revoke this invitation?"
                          description={`${inv.email} will no longer be able to accept this invite.`}
                          confirmLabel="Revoke"
                          aria-label={`Revoke invitation to ${inv.email}`}
                          onConfirm={() => revoke.run(inv.id)}
                        >
                          <Trash2 className="text-destructive" />
                        </ConfirmButton>
                      </div>
                    </TableCell>
                  </PermissionGate>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {latestInvite?.inviteLink && (
            <div className="flex flex-wrap items-center gap-2 border-t border-border bg-info-subtle px-4 py-2.5 text-[12.5px] text-info-subtle-foreground">
              <span>
                Development only — invite link for <span className="font-medium">{latestInvite.email}</span>:
              </span>
              <a
                href={latestInvite.inviteLink}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 font-medium underline"
              >
                <ExternalLink className="size-3.5" />
                Open accept page
              </a>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void navigator.clipboard?.writeText(latestInvite.inviteLink ?? "")}
              >
                Copy link
              </Button>
            </div>
          )}
          {(resend.error || revoke.error) && (
            <p className="border-t border-border px-4 py-2.5 text-[12.5px] font-medium text-destructive">
              {resend.error || revoke.error}
            </p>
          )}
        </Card>
      )}

      <Card className="overflow-hidden">
        <DataToolbar
          searchPlaceholder="Search by name or email..."
          searchValue={controls.q}
          onSearchChange={controls.setQ}
          filters={
            <>
              <FilterSelect
                placeholder="All Roles"
                options={roles.map((r) => r.name)}
                className="w-[172px]"
                value={roles.find((r) => r.code === controls.filters.roleCode)?.name}
                onValueChange={(v) =>
                  controls.setFilter("roleCode", roles.find((r) => r.name === v)?.code)
                }
              />
              <FilterSelect
                placeholder="All Status"
                options={Object.keys(STATUS_VALUES)}
                value={labelForStatus(controls.filters.status)}
                onValueChange={(v) => controls.setFilter("status", v ? STATUS_VALUES[v] : undefined)}
              />
            </>
          }
        />

        <AsyncBoundary
          state={usersState}
          isEmpty={(d) => d.items.length === 0}
          empty={{
            icon: Users2,
            title: controls.activeFilterCount || controls.q ? "No users match your search" : "No users yet",
          }}
        >
          {(data) => (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-4">User</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Godown Access</TableHead>
                  <TableHead>Last Active</TableHead>
                  <TableHead>Status</TableHead>
                  <PermissionGate permission="user.manage">
                    <TableHead className="w-20 pr-4" />
                  </PermissionGate>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell className="pl-4">
                      <span className="flex items-center gap-3">
                        <Avatar>
                          <AvatarFallback>{initials(user.fullName)}</AvatarFallback>
                        </Avatar>
                        <span className="min-w-0">
                          <span className="block font-medium text-foreground">{user.fullName}</span>
                          <span className="block text-caption text-muted-foreground">{user.email}</span>
                        </span>
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.roleCode === "owner" ? "default" : "neutral"}>
                        {user.roleName}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {user.godownNames.join(", ") || "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {user.lastActiveAt ? formatRelativeTime(user.lastActiveAt) : "Never"}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={user.status} />
                    </TableCell>
                    <PermissionGate permission="user.manage">
                      <TableCell className="pr-4">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Manage access for ${user.fullName}`}
                            onClick={() => setManageUser(user)}
                          >
                            <Pencil />
                          </Button>
                          <ConfirmButton
                            variant="ghost"
                            size="icon-sm"
                            tone="destructive"
                            title="Remove this user?"
                            description={`${user.fullName} will immediately lose access. Their history stays on record.`}
                            confirmLabel="Remove"
                            aria-label={`Remove ${user.fullName}`}
                            onConfirm={() => removeUser.run(user.id)}
                          >
                            <Trash2 className="text-destructive" />
                          </ConfirmButton>
                        </div>
                      </TableCell>
                    </PermissionGate>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </AsyncBoundary>

        {removeUser.error && (
          <p className="border-t border-border px-4 py-2.5 text-[12.5px] font-medium text-destructive">
            {removeUser.error}
          </p>
        )}
      </Card>

      {manageUser && (
        <ManageAccessDialog
          user={manageUser}
          roles={roles}
          godowns={godowns}
          onClose={() => setManageUser(null)}
          onSaved={refreshUsers}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------- Godown picker */

function GodownScopeField({
  godowns,
  value,
  onChange,
}: {
  godowns: GodownRow[];
  value: GodownScope;
  onChange: (next: GodownScope) => void;
}) {
  return (
    <div className="space-y-2">
      <Label className="flex items-center gap-2 font-normal">
        <Checkbox
          checked={value.all}
          onCheckedChange={(checked) => onChange({ all: !!checked, godownIds: [] })}
        />
        All godowns
      </Label>
      {!value.all && (
        <div className="max-h-[150px] space-y-1.5 overflow-y-auto rounded-md border border-border p-2.5">
          {godowns.length === 0 && (
            <p className="text-caption text-muted-foreground">No godowns yet.</p>
          )}
          {godowns.map((g) => (
            <Label key={g.id} className="flex items-center gap-2 font-normal">
              <Checkbox
                checked={value.godownIds.includes(g.id)}
                onCheckedChange={(checked) =>
                  onChange({
                    all: false,
                    godownIds: checked
                      ? [...value.godownIds, g.id]
                      : value.godownIds.filter((id) => id !== g.id),
                  })
                }
              />
              {g.name}
            </Label>
          ))}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------- Invite dialog */

function InviteUserDialog({
  roles,
  godowns,
  onInvited,
}: {
  roles: RoleRow[];
  godowns: GodownRow[];
  onInvited: (inv?: Invitation) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [fullName, setFullName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [roleId, setRoleId] = React.useState("");
  const [godownScope, setGodownScope] = React.useState<GodownScope>({ all: true, godownIds: [] });

  const invite = useInviteUser((inv) => {
    onInvited(inv);
    setOpen(false);
    setFullName("");
    setEmail("");
    setRoleId("");
    setGodownScope({ all: true, godownIds: [] });
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) invite.reset();
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus />
          Invite User
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a user</DialogTitle>
          <DialogDescription>
            They&apos;ll get an email with a link to set up their account.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          <div className="space-y-1.5">
            <Label htmlFor="invite-name">Full Name</Label>
            <Input
              id="invite-name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="e.g. Priya Nair"
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="invite-role">Role</Label>
            <Select value={roleId} onValueChange={setRoleId}>
              <SelectTrigger id="invite-role">
                <SelectValue placeholder="Choose a role" />
              </SelectTrigger>
              <SelectContent>
                {roles.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Godown Access</Label>
            <GodownScopeField godowns={godowns} value={godownScope} onChange={setGodownScope} />
          </div>

          <FormError message={invite.error} fieldErrors={invite.fieldErrors} />
        </DialogBody>

        <DialogFooter>
          <Button
            onClick={() => invite.run({ email, fullName, roleId, godownScope })}
            disabled={invite.isPending || !fullName.trim() || !email.trim() || !roleId}
          >
            <Send />
            {invite.isPending ? "Sending Invite..." : "Send Invite"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ---------------------------------------------------- Manage access dialog */

function ManageAccessDialog({
  user,
  roles,
  godowns,
  onClose,
  onSaved,
}: {
  user: User;
  roles: RoleRow[];
  godowns: GodownRow[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [roleId, setRoleId] = React.useState(user.roleId);
  const [status, setStatus] = React.useState<UserStatus>(user.status);
  const [godownScope, setGodownScope] = React.useState<GodownScope>(user.godownScope);

  const update = useUpdateUserAccess(() => {
    onSaved();
    onClose();
  });

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Manage access — {user.fullName}</DialogTitle>
          <DialogDescription>{user.email}</DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          <div className="space-y-1.5">
            <Label htmlFor="manage-role">Role</Label>
            <Select value={roleId} onValueChange={setRoleId}>
              <SelectTrigger id="manage-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {roles.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="manage-status">Status</Label>
            <Select value={status} onValueChange={(v) => setStatus(v as UserStatus)}>
              <SelectTrigger id="manage-status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="inactive">Inactive</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Godown Access</Label>
            <GodownScopeField godowns={godowns} value={godownScope} onChange={setGodownScope} />
          </div>

          <FormError message={update.error} fieldErrors={update.fieldErrors} />
        </DialogBody>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={update.isPending}>
            Cancel
          </Button>
          <Button
            onClick={() => update.run({ userId: user.id, patch: { roleId, status, godownScope } })}
            disabled={update.isPending}
          >
            {update.isPending ? "Saving..." : "Save Changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
