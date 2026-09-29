"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  Building2,
  ExternalLink,
  Pencil,
  LogIn,
  Plus,
  Power,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Users2,
} from "lucide-react";

import { AsyncBoundary, FormError } from "@/components/common/async-state";
import { DataToolbar } from "@/components/common/data-toolbar";
import { EmptyState } from "@/components/common/empty-state";
import { FilterSelect } from "@/components/common/filter-select";
import { AuditEventList } from "@/components/common/audit-trail";
import { KpiCard } from "@/components/common/kpi-card";
import { PageHeader } from "@/components/common/page-header";
import { PermissionGate } from "@/components/common/permission-gate";
import { StatusBadge } from "@/components/common/status-badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDebounced, useListControls, useApiMutation } from "@/hooks/use-api";
import {
  useAddCompanyMember,
  useCompanies,
  useCompany,
  useCompanyInvitations,
  useCompanyMembers,
  useInviteCompanyOwner,
  useOnboardCompany,
  usePlatformActivity,
  usePlatformKpis,
  usePlans,
  usePlatformUsers,
  useRemoveCompanyMember,
  useResendCompanyInvitation,
  useSetCompanyStatus,
  useSetTenantUserStatus,
  useUpdateCompany,
  useUpdatePlatformUserProfile,
  useUserDirectory,
} from "@/hooks/use-admin";
import { useSession } from "@/hooks/use-session";
import { authApi } from "@/lib/api";
import { countActiveOwners } from "@/lib/api/admin.api";
import type { CompanyListRow, CompanyMember, DirectoryUserRow, PlatformUserRow } from "@/lib/api/admin.api";
import { formatDate, formatDateTime } from "@/lib/format";
import { INDIAN_STATES } from "@/lib/gst-states";
import { PlansPanel, planOptions } from "@/components/admin/plans-panel";
import type { AuditLog, Company, CompanyStatus, Id } from "@/types";

/**
 * The platform console — every tenant on InventoryAI, not just this company.
 *
 * Everything here reads `/platform/*`, which answers only to a platform
 * admin's token; a tenant Owner gets 403 on every one of these calls, so the
 * screen is unreachable in substance even if someone routes to it.
 *
 * Two things are worth knowing while reading this:
 *
 *   * Onboarding *invites* the first Owner rather than setting a password
 *     for them — there is deliberately no password field below.
 *   * Suspending takes effect on the tenant's next request (BR-AUTH-04), not
 *     when their token expires, so the confirmation says "immediately" and
 *     means it. It also requires a reason, which their users are shown.
 */

const STATUS_VALUES: Record<string, CompanyStatus> = {
  Active: "active",
  Suspended: "suspended",
};


function initials(name: string) {
  return name.split(" ").map((p) => p[0]).filter(Boolean).join("").slice(0, 2).toUpperCase();
}

export function SystemAdminScreen() {
  // Bumped whenever a company is onboarded or suspended, so the counters and
  // the table both re-read rather than drifting apart.
  const [version, setVersion] = React.useState(0);
  const refresh = React.useCallback(() => setVersion((v) => v + 1), []);
  const kpiState = usePlatformKpis(version);
  const kpis = kpiState.data;
  const companiesForPicker = useCompanies({ limit: 500 });

  return (
    <div className="space-y-5" data-testid="system-admin-screen">
      <PageHeader
        title="System Admin"
        description="Platform-wide view across every company on InventoryAI"
      />

      <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-4">
        <KpiCard label="Companies" value={String(kpis?.companies ?? "—")} icon={Building2} />
        <KpiCard
          label="Active Companies"
          value={String(kpis?.activeCompanies ?? "—")}
          icon={ShieldCheck}
          tone="success"
        />
        <KpiCard label="Total Users" value={String(kpis?.users ?? "—")} icon={Users2} tone="info" />
        <KpiCard
          label="Suspended"
          value={String(kpis?.suspendedCompanies ?? "—")}
          icon={ShieldX}
          tone="destructive"
        />
      </div>

      <Tabs defaultValue="companies">
        <TabsList>
          <TabsTrigger value="companies">Companies</TabsTrigger>
          <TabsTrigger value="users" data-testid="system-admin-users-tab">
            Users
          </TabsTrigger>
          <TabsTrigger value="impersonate">Impersonate</TabsTrigger>
          <TabsTrigger value="plans">Plans</TabsTrigger>
          <TabsTrigger value="activity">Platform Activity</TabsTrigger>
        </TabsList>

        <TabsContent value="companies" className="mt-4">
          <CompaniesTab version={version} onChanged={refresh} />
        </TabsContent>

        <TabsContent value="users" className="mt-4">
          <UsersTab companies={companiesForPicker.data?.items ?? []} onChanged={refresh} />
        </TabsContent>

        <TabsContent value="impersonate" className="mt-4">
          <ImpersonateTab companies={companiesForPicker.data?.items ?? []} />
        </TabsContent>

        <TabsContent value="plans" className="mt-4">
          <PlansPanel onChanged={refresh} />
        </TabsContent>

        <TabsContent value="activity" className="mt-4">
          <PlatformActivityTab version={version} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/* -------------------------------------------------------------- Companies */

function CompaniesTab({ version, onChanged }: { version: number; onChanged: () => void }) {
  const plans = usePlans();
  const controls = useListControls({ sort: "name" });
  const state = useCompanies({ ...controls.params, _v: version } as never);

  const reload = React.useCallback(() => {
    state.refresh();
    onChanged();
  }, [state, onChanged]);

  const labelForStatus = (value?: string) =>
    Object.keys(STATUS_VALUES).find((key) => STATUS_VALUES[key] === value);

  return (
    <Card className="overflow-hidden">
      <DataToolbar
        searchPlaceholder="Search companies by name, GSTIN, city, state..."
        searchValue={controls.q}
        onSearchChange={controls.setQ}
        filters={
          <>
            <FilterSelect
              placeholder="All Plans"
              options={(plans.data ?? []).map((p) => p.name)}
              value={controls.filters.plan}
              onValueChange={(v) => controls.setFilter("plan", v)}
            />
            <FilterSelect
              placeholder="All Status"
              options={Object.keys(STATUS_VALUES)}
              value={labelForStatus(controls.filters.status)}
              onValueChange={(v) => controls.setFilter("status", v ? STATUS_VALUES[v] : undefined)}
            />
          </>
        }
        trailing={
          <PermissionGate permission="platform.companies.manage">
            <OnboardCompanyDialog onDone={reload} />
          </PermissionGate>
        }
      />

      <AsyncBoundary
        state={state}
        isEmpty={(d) => d.items.length === 0}
        empty={{ icon: Building2, title: "No companies match your search" }}
      >
        {(data) => (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Company</TableHead>
                <TableHead>Location</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead className="text-right">Users</TableHead>
                <TableHead className="text-right">SKUs</TableHead>
                <TableHead>Onboarded</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="pr-4 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((c) => (
                <TableRow key={c.id} data-testid={`company-row-${c.id}`}>
                  <TableCell className="pl-4">
                    <span className="block font-medium text-foreground">{c.name}</span>
                    <span className="block text-caption text-muted-foreground">
                      {c.ownerName || c.ownerEmail}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {[c.city, c.stateName].filter(Boolean).join(", ")}
                  </TableCell>
                  <TableCell>
                    <Badge variant="neutral">{c.plan}</Badge>
                  </TableCell>
                  <TableCell className="text-right tabular text-foreground">{c.userCount}</TableCell>
                  <TableCell className="text-right tabular text-foreground">{c.skuCount}</TableCell>
                  <TableCell className="text-muted-foreground">{formatDate(c.onboardedOn)}</TableCell>
                  <TableCell>
                    <StatusBadge status={c.status} />
                    {c.status === "suspended" && c.suspendedReason && (
                      <span className="mt-0.5 block text-caption text-muted-foreground">
                        {c.suspendedReason}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="pr-4">
                    <div className="flex justify-end gap-2">
                      <ManageCompanyButton company={c} onChanged={reload} />
                      <PermissionGate permission="platform.companies.manage">
                        <CompanyStatusButton company={c} onDone={reload} />
                      </PermissionGate>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </AsyncBoundary>
    </Card>
  );
}

/**
 * Suspend / reactivate.
 *
 * Suspending opens a dialog rather than a plain confirm because the server
 * requires a reason and the tenant's users are shown it; reactivating needs
 * nothing, so it just asks once.
 */
function CompanyStatusButton({ company, onDone }: { company: CompanyListRow; onDone: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const suspending = company.status === "active";
  const setStatus = useSetCompanyStatus(() => {
    setOpen(false);
    setReason("");
    onDone();
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setReason("");
          setStatus.reset();
        }
      }}
    >
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        data-testid={`company-status-${company.id}`}
      >
        {suspending ? "Suspend" : "Reactivate"}
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {suspending ? `Suspend ${company.name}?` : `Reactivate ${company.name}?`}
          </DialogTitle>
          <DialogDescription>
            {suspending
              ? "Everyone at this company loses access on their very next request — signed-in users included."
              : "This company's users regain access immediately."}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3.5">
          {suspending && (
            <div className="space-y-1.5">
              <Label htmlFor="suspend-reason">Reason</Label>
              <Textarea
                id="suspend-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Subscription unpaid since August"
                autoFocus
              />
            </div>
          )}
          <FormError message={setStatus.error} fieldErrors={setStatus.fieldErrors} />
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={setStatus.isPending}>
            Cancel
          </Button>
          <Button
            variant={suspending ? "destructive" : "default"}
            disabled={setStatus.isPending || (suspending && reason.trim().length < 3)}
            data-testid={`company-status-confirm-${company.id}`}
            onClick={() =>
              setStatus.run({
                companyId: company.id,
                status: suspending ? "suspended" : "active",
                reason: suspending ? reason : undefined,
              })
            }
          >
            {setStatus.isPending ? "Working..." : suspending ? "Suspend" : "Reactivate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* --------------------------------------------------------- Manage tenant */

/**
 * The two System Admin gaps the audit flagged: editing a tenant's own
 * profile fields, and seeing/managing its users, from the console rather
 * than by impersonating in. Both read/write endpoints already existed on
 * the backend (`GET/PATCH /platform/companies/{id}`) before this — only
 * the user-status toggle (`PATCH /platform/users/{id}`) is new, and it is
 * deliberately narrower than the tenant-side user editor: status only, no
 * role or godown-scope changes from here (see `console_service.py` for why).
 */
function ManageCompanyButton({ company, onChanged }: { company: CompanyListRow; onChanged: () => void }) {
  const [open, setOpen] = React.useState(false);
  // Changes made inside the dialog are reported to the page only once it
  // closes. Reporting them straight away re-keyed the companies query,
  // which briefly unmounted the table — and this dialog with it, so every
  // save, status change or link closed the dialog under the user.
  const dirty = React.useRef(false);
  const markChanged = React.useCallback(() => {
    dirty.current = true;
  }, []);
  const queryClient = useQueryClient();
  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next && dirty.current) {
      dirty.current = false;
      // Drop the cached tenant row so the next "Manage" fetches fresh data
      // instead of showing the pre-save values from the 30s query cache.
      queryClient.removeQueries({ queryKey: ["company", company.id] });
      queryClient.invalidateQueries({ queryKey: ["user-directory"] });
      onChanged();
    }
  };
  // Saving the details form closes the dialog; closing reloads the list.
  const handleSaved = () => {
    dirty.current = true;
    handleOpenChange(false);
  };
  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} data-testid={`manage-company-${company.id}`}>
        <Settings2 />
        Manage
      </Button>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{company.name}</DialogTitle>
          <DialogDescription>Tenant details and users, as the platform sees them.</DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[65vh] overflow-y-auto">
          {open && <ManageCompanyBody companyId={company.id} onChanged={markChanged} onSaved={handleSaved} />}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ManageCompanyBody({
  companyId,
  onChanged,
  onSaved,
}: {
  companyId: Id;
  onChanged: () => void;
  onSaved: () => void;
}) {
  const state = useCompany(companyId);
  const usersState = usePlatformUsers(companyId);
  const membersState = useCompanyMembers(companyId);
  // Linked Owners count toward "last Owner" too (BR-AUTH-10). Until both
  // lists have loaded the count is unknown, so nothing is disabled early.
  const ownerCount =
    usersState.data && membersState.data ? countActiveOwners(usersState.data, membersState.data) : undefined;

  return (
    <Tabs defaultValue="details">
      <TabsList>
        <TabsTrigger value="details">Details</TabsTrigger>
        <TabsTrigger value="users">Users</TabsTrigger>
        <TabsTrigger value="linked" data-testid="manage-linked-tab">
          Linked owners
        </TabsTrigger>
      </TabsList>
      <TabsContent value="details" className="mt-4">
        <AsyncBoundary state={state}>
          {(company) => <CompanyDetailsForm company={company} onChanged={onSaved} />}
        </AsyncBoundary>
      </TabsContent>
      <TabsContent value="users" className="mt-4 space-y-5">
        <PendingInvitationsPanel companyId={companyId} onChanged={onChanged} />
        <AsyncBoundary
          state={usersState}
          isEmpty={(d) => d.length === 0}
          empty={{ icon: Users2, title: "No users at this company" }}
        >
          {(users) => (
            <CompanyUsersTable
              users={users}
              ownerCount={ownerCount}
              onDone={() => {
                usersState.refresh();
                onChanged();
              }}
            />
          )}
        </AsyncBoundary>
      </TabsContent>
      <TabsContent value="linked" className="mt-4">
        <LinkedOwnersPanel companyId={companyId} onChanged={onChanged} />
      </TabsContent>
    </Tabs>
  );
}

/**
 * Invitations nobody has accepted yet. A freshly onboarded company has only
 * its Owner's invitation and no users, so this is the one place the platform
 * admin can get that link out again. "Resend" issues a new link (the old one
 * stops working) and emails it; the link itself is shown only in development,
 * because the server keeps just a hash of it.
 */
function PendingInvitationsPanel({ companyId, onChanged }: { companyId: Id; onChanged: () => void }) {
  const state = useCompanyInvitations(companyId);
  const [issued, setIssued] = React.useState<{ email: string; link?: string; isNew: boolean } | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [inviting, setInviting] = React.useState(false);
  const [inviteForm, setInviteForm] = React.useState({ fullName: "", email: "" });
  // Chrome ignores autoComplete="off" for name/email-looking fields and shows saved
  // addresses. Fields stay readOnly until the user focuses them, so autofill never
  // attaches; ids/names avoid the "name"/"email" keywords Chrome's heuristics match.
  const [inviteUnlocked, setInviteUnlocked] = React.useState({ a: false, b: false });
  const resend = useResendCompanyInvitation((result) => {
    setIssued({ email: result.email, link: result.inviteLink, isNew: false });
    setCopied(false);
    state.refresh();
  });
  const invite = useInviteCompanyOwner((result) => {
    setIssued({ email: result.email, link: result.inviteLink, isNew: true });
    setCopied(false);
    setInviting(false);
    setInviteUnlocked({ a: false, b: false });
    setInviteForm({ fullName: "", email: "" });
    state.refresh();
    onChanged();
  });

  const invitations = state.data ?? [];
  if (state.isLoading) return null;

  return (
    <div className="space-y-2" data-testid="pending-invitations">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-[13px] font-medium text-foreground">
          {invitations.length > 0 ? "Pending invitations" : ""}
        </h4>
        <PermissionGate permission="platform.companies.manage">
          {!inviting && (
            <Button variant="outline" size="sm" onClick={() => setInviting(true)} data-testid="invite-owner-open">
              <Plus />
              Invite owner
            </Button>
          )}
        </PermissionGate>
      </div>
      {inviting && (
        <div className="space-y-2.5 rounded-md border border-border p-3" data-testid="invite-owner-form">
          <p className="text-[12.5px] text-muted-foreground">
            Invite another Owner to this company. To replace the current Owner, invite the new one first —
            the last Owner can be deactivated only once someone else can manage the company.
          </p>
          <div className="grid gap-2.5 sm:grid-cols-2">
            <Field label="Full name" id="io-field-a" required>
              <Input
                id="io-field-a"
                name="io-field-a"
                type="text"
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="words"
                spellCheck={false}
                data-lpignore="true"
                data-1p-ignore
                data-form-type="other"
                readOnly={!inviteUnlocked.a}
                onFocus={() => setInviteUnlocked((u) => (u.a ? u : { ...u, a: true }))}
                value={inviteForm.fullName}
                onChange={(e) => setInviteForm((f) => ({ ...f, fullName: e.target.value }))}
                data-testid="invite-owner-name"
                autoFocus
              />
            </Field>
            <Field label="Email" id="io-field-b" required>
              <Input
                id="io-field-b"
                type="text"
                inputMode="email"
                name="io-field-b"
                autoComplete="off"
                autoCapitalize="none"
                data-form-type="other"
                readOnly={!inviteUnlocked.b}
                onFocus={() => setInviteUnlocked((u) => (u.b ? u : { ...u, b: true }))}
                autoCorrect="off"
                spellCheck={false}
                data-lpignore="true"
                data-1p-ignore
                value={inviteForm.email}
                onChange={(e) => setInviteForm((f) => ({ ...f, email: e.target.value }))}
                data-testid="invite-owner-email"
              />
            </Field>
          </div>
          <FormError message={invite.error} fieldErrors={invite.fieldErrors} />
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setInviting(false);
                setInviteUnlocked({ a: false, b: false });
                invite.reset();
              }}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={invite.isPending || inviteForm.fullName.trim().length < 2 || !inviteForm.email.trim()}
              onClick={() => invite.run({ companyId, ...inviteForm })}
              data-testid="invite-owner-submit"
            >
              {invite.isPending ? "Sending..." : "Send invite"}
            </Button>
          </div>
        </div>
      )}
      {invitations.length > 0 && (
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="pl-4">Invited</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Expires</TableHead>
            <PermissionGate permission="platform.companies.manage">
              <TableHead className="pr-4 text-right">Actions</TableHead>
            </PermissionGate>
          </TableRow>
        </TableHeader>
        <TableBody>
          {invitations.map((inv) => (
            <TableRow key={inv.id} data-testid={`pending-invite-${inv.email}`}>
              <TableCell className="pl-4">
                <span className="block font-medium text-foreground">{inv.fullName}</span>
                <span className="block text-caption text-muted-foreground">{inv.email}</span>
              </TableCell>
              <TableCell className="text-muted-foreground">{inv.roleName}</TableCell>
              <TableCell className={inv.isExpired ? "font-medium text-destructive" : "text-muted-foreground"}>
                {inv.isExpired ? "Expired " : ""}
                {formatDate(inv.expiresAt)}
              </TableCell>
              <PermissionGate permission="platform.companies.manage">
                <TableCell className="pr-4">
                  <div className="flex justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={resend.isPending}
                      data-testid={`resend-invite-${inv.email}`}
                      onClick={() => resend.run({ companyId, invitationId: inv.id })}
                    >
                      {resend.isPending ? "Sending..." : "Resend invite"}
                    </Button>
                  </div>
                </TableCell>
              </PermissionGate>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      )}
      <FormError message={resend.error} fieldErrors={resend.fieldErrors} />
      {issued && (
        <div
          className="space-y-2 rounded-md border border-border bg-info-subtle px-3.5 py-2.5 text-[12.5px] text-info-subtle-foreground"
          data-testid="resent-invite"
        >
          <p>
            {issued.isNew ? "An invitation was emailed to " : "A new invitation was emailed to "}
            <span className="font-medium">{issued.email}</span>.
            {issued.isNew ? "" : " Any earlier link no longer works."}
          </p>
          {issued.link && (
            <div className="flex flex-wrap items-center gap-2">
              <span>Development only — invite link:</span>
              <a
                href={issued.link}
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
                onClick={() => {
                  void navigator.clipboard?.writeText(issued.link ?? "");
                  setCopied(true);
                }}
              >
                {copied ? "Copied" : "Copy link"}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * BR-AUTH-13: people whose login belongs to another company but who can
 * switch into this one from their header — "one owner, several
 * businesses". Console-only by design: letting a tenant add someone from
 * another tenant would mean reaching into that tenant's user base.
 */
function LinkedOwnersPanel({ companyId, onChanged }: { companyId: Id; onChanged: () => void }) {
  const state = useCompanyMembers(companyId);
  const usersState = usePlatformUsers(companyId);
  const ownerCount =
    state.data && usersState.data ? countActiveOwners(usersState.data, state.data) : undefined;
  const [email, setEmail] = React.useState("");
  const add = useAddCompanyMember(() => {
    setEmail("");
    state.refresh();
    onChanged();
  });

  return (
    <div className="space-y-4">
      <p className="text-[12.5px] text-muted-foreground">
        Give an existing login Owner access to this company. They keep their own company and switch
        between the two from the account menu — no second account, no new password.
      </p>
      <PermissionGate permission="platform.companies.manage">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="link-owner-email">Email of an existing user</Label>
            <Input
              id="link-owner-email"
              type="email"
              placeholder="owner@theircompany.in"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              data-testid="link-owner-email"
            />
          </div>
          <Button
            disabled={!email.trim() || add.isPending}
            onClick={() => add.run({ companyId, email })}
            data-testid="link-owner-submit"
          >
            <Plus />
            {add.isPending ? "Linking..." : "Link as Owner"}
          </Button>
        </div>
        <FormError message={add.error} fieldErrors={add.fieldErrors} />
      </PermissionGate>
      <AsyncBoundary
        state={state}
        isEmpty={(d) => d.length === 0}
        empty={{ icon: Users2, title: "No linked owners", description: "Only this company's own users can sign in to it." }}
      >
        {(members) => (
          <LinkedOwnersTable
            companyId={companyId}
            members={members}
            ownerCount={ownerCount}
            onDone={() => {
              state.refresh();
              usersState.refresh();
              onChanged();
            }}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

function LinkedOwnersTable({
  companyId,
  members,
  ownerCount,
  onDone,
}: {
  companyId: Id;
  members: CompanyMember[];
  ownerCount?: number;
  onDone: () => void;
}) {
  const remove = useRemoveCompanyMember(onDone);

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="pl-4">Person</TableHead>
            <TableHead>Home company</TableHead>
            <TableHead>Role here</TableHead>
            <TableHead>Linked</TableHead>
            <PermissionGate permission="platform.companies.manage">
              <TableHead className="pr-4 text-right">Actions</TableHead>
            </PermissionGate>
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.map((m) => (
            <TableRow key={m.userId} data-testid={`linked-owner-row-${m.email}`}>
              <TableCell className="pl-4">
                <span className="block font-medium text-foreground">{m.fullName}</span>
                <span className="block text-caption text-muted-foreground">{m.email}</span>
              </TableCell>
              <TableCell className="text-muted-foreground">{m.homeCompanyName || "—"}</TableCell>
              <TableCell className="text-muted-foreground">{m.roleName || m.roleCode}</TableCell>
              <TableCell className="text-muted-foreground">{formatDate(m.addedAt)}</TableCell>
              <PermissionGate permission="platform.companies.manage">
                <TableCell className="pr-4">
                  <div className="flex flex-col items-end gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={remove.isPending || isLastOwner(m.roleCode, m.status, ownerCount)}
                      title={isLastOwner(m.roleCode, m.status, ownerCount) ? LAST_OWNER_HINT : undefined}
                      data-testid={`linked-owner-remove-${m.email}`}
                      onClick={() => remove.run({ companyId, userId: m.userId })}
                    >
                      <Power />
                      Remove access
                    </Button>
                    {isLastOwner(m.roleCode, m.status, ownerCount) && (
                      <span className="text-caption text-muted-foreground">Last owner</span>
                    )}
                  </div>
                </TableCell>
              </PermissionGate>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <FormError message={remove.error} />
    </>
  );
}

function CompanyDetailsForm({ company, onChanged }: { company: CompanyListRow; onChanged: () => void }) {
  const plans = usePlans();
  const [form, setForm] = React.useState({
    name: company.name,
    legalName: company.legalName ?? "",
    gstin: company.gstin ?? "",
    city: company.city ?? "",
    email: company.email ?? "",
    phone: company.phone ?? "",
    plan: company.plan,
  });
  const update = useUpdateCompany(() => onChanged());

  const set = (key: keyof typeof form) => (value: string) => setForm((f) => ({ ...f, [key]: value }));

  return (
    <div className="space-y-3.5">
      <div className="grid gap-3.5 sm:grid-cols-2">
        <Field label="Company name" id="mc-name" required>
          <Input id="mc-name" value={form.name} onChange={(e) => set("name")(e.target.value)} />
        </Field>
        <Field label="Legal name" id="mc-legal">
          <Input id="mc-legal" value={form.legalName} onChange={(e) => set("legalName")(e.target.value)} />
        </Field>
        <Field label="GSTIN" id="mc-gstin">
          <Input id="mc-gstin" value={form.gstin} onChange={(e) => set("gstin")(e.target.value.toUpperCase())} />
        </Field>
        <Field label="City" id="mc-city">
          <Input id="mc-city" value={form.city} onChange={(e) => set("city")(e.target.value)} />
        </Field>
        <Field label="Email" id="mc-email">
          <Input id="mc-email" type="email" value={form.email} onChange={(e) => set("email")(e.target.value)} />
        </Field>
        <Field label="Phone" id="mc-phone">
          <Input id="mc-phone" value={form.phone} onChange={(e) => set("phone")(e.target.value)} />
        </Field>
        <Field label="Plan" id="mc-plan">
          <Select value={form.plan} onValueChange={(v) => set("plan")(v as Company["plan"])}>
            <SelectTrigger id="mc-plan">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {planOptions(plans.data, company.plan).map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>
      <div className="space-y-0.5 text-caption text-muted-foreground">
        <p>Owner: {company.ownerName || company.ownerEmail || "—"}</p>
        <p>
          Onboarded {formatDate(company.onboardedOn)} · {company.userCount} users · {company.skuCount} SKUs
        </p>
      </div>
      <FormError message={update.error} fieldErrors={update.fieldErrors} />
      <PermissionGate permission="platform.companies.manage">
        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={update.isPending}
            data-testid="manage-company-save"
            onClick={() =>
              update.run({
                companyId: company.id,
                patch: {
                  name: form.name,
                  legalName: form.legalName,
                  gstin: form.gstin,
                  city: form.city,
                  email: form.email,
                  phone: form.phone,
                  plan: form.plan,
                },
              })
            }
          >
            {update.isPending ? "Saving..." : "Save changes"}
          </Button>
        </div>
      </PermissionGate>
    </div>
  );
}

function CompanyUsersTable({
  users,
  ownerCount,
  onDone,
}: {
  users: PlatformUserRow[];
  ownerCount?: number;
  onDone: () => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-4">User</TableHead>
          <TableHead>Role</TableHead>
          <TableHead>Status</TableHead>
          <PermissionGate permission="platform.companies.manage">
            <TableHead className="pr-4 text-right">Actions</TableHead>
          </PermissionGate>
        </TableRow>
      </TableHeader>
      <TableBody>
        {users.map((u) => (
          <TableRow key={u.id} data-testid={`manage-user-row-${u.email}`}>
            <TableCell className="pl-4">
              <span className="block font-medium text-foreground">{u.fullName}</span>
              <span className="block text-caption text-muted-foreground">{u.email}</span>
            </TableCell>
            <TableCell className="text-muted-foreground">{u.roleName || u.roleCode}</TableCell>
            <TableCell>
              <StatusBadge status={u.status} />
            </TableCell>
            <PermissionGate permission="platform.companies.manage">
              <TableCell className="pr-4">
                <div className="flex justify-end">
                  <UserStatusButton user={u} lastOwner={isLastOwner(u.roleCode, u.status, ownerCount)} onDone={onDone} />
                </div>
              </TableCell>
            </PermissionGate>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * Status only — no role or godown-scope editing from the console (see the
 * backend note on `update_user_status`). The server still refuses to
 * deactivate a tenant's last active Owner and ends the user's live sessions
 * the moment it does deactivate someone.
 */
const LAST_OWNER_HINT = "This is the last active Owner. Invite or link another Owner first.";

/** BR-AUTH-10, client side: only disables a button the server would refuse. */
function isLastOwner(roleCode: string, status: string, ownerCount: number | undefined): boolean {
  return roleCode === "owner" && status === "active" && ownerCount !== undefined && ownerCount <= 1;
}

function UserStatusButton({
  user,
  lastOwner,
  onDone,
}: {
  user: Pick<PlatformUserRow, "id" | "email" | "status">;
  lastOwner: boolean;
  onDone: () => void;
}) {
  const activating = user.status !== "active";
  const setStatus = useSetTenantUserStatus(onDone);
  const blocked = !activating && lastOwner;

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant="outline"
        size="sm"
        disabled={setStatus.isPending || blocked}
        title={blocked ? LAST_OWNER_HINT : undefined}
        data-testid={`manage-user-status-${user.email}`}
        onClick={() => setStatus.run({ userId: user.id, status: activating ? "active" : "inactive" })}
      >
        <Power />
        {setStatus.isPending ? "Working..." : activating ? "Activate" : "Deactivate"}
      </Button>
      {blocked && <span className="text-caption text-muted-foreground">Last owner — invite another first</span>}
      {setStatus.error && (
        <span className="max-w-[260px] text-right text-caption font-medium text-destructive">{setStatus.error}</span>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- All users */

const USER_STATUS_VALUES: Record<string, string> = {
  Active: "active",
  Inactive: "inactive",
};

/**
 * Every tenant user on the platform, in one place. Each row lists all the
 * companies the person can work in — their home company plus any they are
 * linked to — and the company filter matches either, so a linked Owner
 * shows up under both companies.
 *
 * Deactivating goes through the same endpoint as the Manage dialog, so the
 * BR-AUTH-10 "last Owner" rule (linked Owners included) still applies; the
 * server's refusal is shown under the button.
 */
function UsersTab({ companies, onChanged }: { companies: CompanyListRow[]; onChanged: () => void }) {
  const [q, setQ] = React.useState("");
  const [companyId, setCompanyId] = React.useState("all");
  const [status, setStatus] = React.useState<string | undefined>(undefined);
  const debouncedQ = useDebounced(q, 300);
  const state = useUserDirectory({
    q: debouncedQ || undefined,
    companyId: companyId === "all" ? undefined : companyId,
    status,
  });

  const queryClient = useQueryClient();
  const reload = React.useCallback(() => {
    // Every filter combination is cached under its own key, so refreshing
    // only the current one left e.g. the "Inactive" view showing the list
    // from before the change. Invalidate them all.
    queryClient.invalidateQueries({ queryKey: ["user-directory"] });
    // The Manage dialog and Impersonate tab read the same people under
    // other keys; drop those so they don't show the pre-change status.
    queryClient.invalidateQueries({ queryKey: ["platform-users"] });
    queryClient.invalidateQueries({ queryKey: ["company-members"] });
    onChanged();
  }, [onChanged, queryClient]);

  const labelForStatus = (value?: string) =>
    Object.keys(USER_STATUS_VALUES).find((key) => USER_STATUS_VALUES[key] === value);

  return (
    <Card className="overflow-hidden" data-testid="system-admin-users">
      <DataToolbar
        searchPlaceholder="Search users by name or email..."
        searchValue={q}
        onSearchChange={setQ}
        filters={
          <>
            <Select value={companyId} onValueChange={setCompanyId}>
              <SelectTrigger size="sm" className="w-[200px]" data-testid="users-company-filter">
                <SelectValue placeholder="All Companies" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Companies</SelectItem>
                {companies.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FilterSelect
              placeholder="All Status"
              options={Object.keys(USER_STATUS_VALUES)}
              value={labelForStatus(status) ?? "all"}
              onValueChange={(v) => setStatus(v && v !== "all" ? USER_STATUS_VALUES[v] : undefined)}
            />
          </>
        }
      />

      <AsyncBoundary
        state={state}
        isEmpty={(d) => d.length === 0}
        empty={{ icon: Users2, title: "No users match your filters" }}
      >
        {(users) => (
          <>
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-4">User</TableHead>
                  <TableHead>Companies</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last login</TableHead>
                  <PermissionGate permission="platform.companies.manage">
                    <TableHead className="pr-4 text-right">Actions</TableHead>
                  </PermissionGate>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow key={u.id} data-testid={`directory-row-${u.email}`}>
                    <TableCell className="pl-4">
                      <span className="flex items-center gap-3">
                        <Avatar>
                          <AvatarFallback>{initials(u.fullName)}</AvatarFallback>
                        </Avatar>
                        <span className="min-w-0">
                          <span className="block font-medium text-foreground">{u.fullName}</span>
                          <span className="block text-caption text-muted-foreground">{u.email}</span>
                        </span>
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex max-w-[360px] flex-wrap gap-1.5">
                        {u.companies.length === 0 && <span className="text-muted-foreground">—</span>}
                        {u.companies.map((c) => (
                          <Badge
                            key={c.companyId}
                            variant={c.isHome ? "info" : "neutral"}
                            title={
                              c.isHome
                                ? `Home company · ${c.roleName}`
                                : `Linked · ${c.roleName}${c.status !== "active" ? ` · ${c.status}` : ""}`
                            }
                          >
                            {c.companyName}
                            <span className="font-normal opacity-75">
                              {" "}
                              · {c.roleName}
                              {c.isHome ? "" : " (linked)"}
                            </span>
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={u.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {u.lastLoginAt ? formatDateTime(u.lastLoginAt) : "Never"}
                    </TableCell>
                    <PermissionGate permission="platform.companies.manage">
                      <TableCell className="pr-4">
                        <div className="flex items-start justify-end gap-2">
                          <EditUserDialog user={u} onDone={reload} />
                          <UserStatusButton user={u} lastOwner={false} onDone={reload} />
                        </div>
                      </TableCell>
                    </PermissionGate>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="border-t border-border px-4 py-2.5 text-caption text-muted-foreground">
              {users.length} {users.length === 1 ? "user" : "users"}
              {users.length >= 1000 ? " (showing the first 1000 — narrow the search)" : ""}
            </p>
          </>
        )}
      </AsyncBoundary>
    </Card>
  );
}

/** Name and phone only. Email is the login (changing it needs the person to
 * confirm the new address); role changes stay on the tenant's Users screen. */
function EditUserDialog({ user, onDone }: { user: DirectoryUserRow; onDone: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState({ fullName: user.fullName, phone: user.phone ?? "" });
  const update = useUpdatePlatformUserProfile(() => {
    setOpen(false);
    onDone();
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setForm({ fullName: user.fullName, phone: user.phone ?? "" });
        else update.reset();
      }}
    >
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        data-testid={`directory-edit-${user.email}`}
      >
        <Pencil />
        Edit
      </Button>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit user</DialogTitle>
          <DialogDescription>
            Correct this person&apos;s name or phone. Roles are changed by the company&apos;s Owner.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3.5">
          <Field label="Email" id="edit-user-email">
            <Input id="edit-user-email" value={user.email} readOnly disabled />
          </Field>
          <Field label="Full name" id="edit-user-name" required>
            <Input
              id="edit-user-name"
              value={form.fullName}
              onChange={(e) => setForm((f) => ({ ...f, fullName: e.target.value }))}
              data-testid="edit-user-name"
            />
          </Field>
          <Field label="Phone" id="edit-user-phone">
            <Input
              id="edit-user-phone"
              value={form.phone}
              onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
            />
          </Field>
          <FormError message={update.error} fieldErrors={update.fieldErrors} />
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            disabled={update.isPending || form.fullName.trim().length < 2}
            onClick={() => update.run({ userId: user.id, ...form })}
            data-testid="edit-user-save"
          >
            {update.isPending ? "Saving..." : "Save changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------------------------------------- Onboarding */

const EMPTY_ONBOARD = {
  name: "",
  legalName: "",
  gstin: "",
  stateCode: "",
  city: "",
  email: "",
  phone: "",
  plan: "Trial" as Company["plan"],
  ownerEmail: "",
  ownerFullName: "",
};

function OnboardCompanyDialog({ onDone }: { onDone: () => void }) {
  const plans = usePlans();
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState(EMPTY_ONBOARD);
  const [invited, setInvited] = React.useState<{ email: string; token?: string; linked: boolean } | null>(null);

  const onboard = useOnboardCompany((result) => {
    setInvited({ email: result.ownerEmail, token: result.invitationToken, linked: result.ownerLinked });
    setForm(EMPTY_ONBOARD);
    onDone();
  });

  const set = (key: keyof typeof EMPTY_ONBOARD) => (value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setForm(EMPTY_ONBOARD);
          setInvited(null);
          onboard.reset();
        }
      }}
    >
      <Button size="sm" onClick={() => setOpen(true)} data-testid="onboard-company">
        <Plus />
        Onboard Company
      </Button>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Onboard a company</DialogTitle>
          <DialogDescription>
            Creates the tenant with its default godown and numbering series, then invites the
            first Owner. You never set their password — they choose it from the invite link.
          </DialogDescription>
        </DialogHeader>

        {invited ? (
          <>
            <DialogBody className="space-y-2.5">
              {invited.linked ? (
                <p className="text-[13px] text-foreground" data-testid="onboard-linked">
                  Created. <span className="font-medium">{invited.email}</span> already has a login, so
                  this company was linked to it as Owner — they can switch into it from their account
                  menu. No invitation was sent.
                </p>
              ) : (
                <p className="text-[13px] text-foreground">
                  Created. An invitation is on its way to{" "}
                  <span className="font-medium">{invited.email}</span>.
                </p>
              )}
              {invited.token && (
                <div className="space-y-1.5">
                  <Label htmlFor="invite-token">Invite link (development only)</Label>
                  <Input
                    id="invite-token"
                    readOnly
                    value={`/accept-invitation?token=${invited.token}`}
                    data-testid="onboard-invite-token"
                  />
                </div>
              )}
            </DialogBody>
            <DialogFooter>
              <Button onClick={() => setOpen(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogBody className="grid gap-3.5 sm:grid-cols-2">
              <Field label="Company name" id="onb-name" required>
                <Input
                  id="onb-name"
                  value={form.name}
                  onChange={(e) => set("name")(e.target.value)}
                  data-testid="onboard-name"
                  autoFocus
                />
              </Field>
              <Field label="Legal name" id="onb-legal">
                <Input id="onb-legal" value={form.legalName} onChange={(e) => set("legalName")(e.target.value)} />
              </Field>
              <Field label="State" id="onb-state" required>
                <Select value={form.stateCode} onValueChange={set("stateCode")}>
                  <SelectTrigger id="onb-state" data-testid="onboard-state">
                    <SelectValue placeholder="Choose a state" />
                  </SelectTrigger>
                  <SelectContent>
                    {INDIAN_STATES.map((s) => (
                      <SelectItem key={s.code} value={s.code}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="City" id="onb-city">
                <Input id="onb-city" value={form.city} onChange={(e) => set("city")(e.target.value)} />
              </Field>
              <Field label="GSTIN" id="onb-gstin">
                <Input
                  id="onb-gstin"
                  value={form.gstin}
                  onChange={(e) => set("gstin")(e.target.value.toUpperCase())}
                  placeholder="15 characters"
                />
              </Field>
              <Field label="Plan" id="onb-plan">
                <Select value={form.plan} onValueChange={(v) => set("plan")(v)}>
                  <SelectTrigger id="onb-plan">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {planOptions(plans.data).map((p) => (
                      <SelectItem key={p} value={p}>
                        {p}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Owner's name" id="onb-owner-name" required>
                <Input
                  id="onb-owner-name"
                  value={form.ownerFullName}
                  onChange={(e) => set("ownerFullName")(e.target.value)}
                  data-testid="onboard-owner-name"
                />
              </Field>
              <Field label="Owner's email" id="onb-owner-email" required>
                <Input
                  id="onb-owner-email"
                  type="email"
                  value={form.ownerEmail}
                  onChange={(e) => set("ownerEmail")(e.target.value)}
                  data-testid="onboard-owner-email"
                />
              </Field>
              <div className="sm:col-span-2">
                <FormError message={onboard.error} fieldErrors={onboard.fieldErrors} />
              </div>
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)} disabled={onboard.isPending}>
                Cancel
              </Button>
              <Button
                disabled={onboard.isPending}
                data-testid="onboard-submit"
                onClick={() =>
                  onboard.run({
                    ...form,
                    stateName: INDIAN_STATES.find((s) => s.code === form.stateCode)?.name ?? "",
                  })
                }
              >
                {onboard.isPending ? "Creating..." : "Create & invite Owner"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  id,
  required,
  children,
}: {
  label: string;
  id: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {label}
        {required && <span className="text-destructive"> *</span>}
      </Label>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------ Impersonate */

function ImpersonateTab({ companies }: { companies: CompanyListRow[] }) {
  const [companyId, setCompanyId] = React.useState("");
  const usersState = usePlatformUsers(companyId || undefined);

  return (
    <div className="space-y-4">
      <div className="max-w-xs space-y-1.5">
        <Label htmlFor="imp-company">Company</Label>
        <Select value={companyId} onValueChange={setCompanyId}>
          <SelectTrigger id="imp-company" data-testid="impersonate-company">
            <SelectValue placeholder="Choose a company" />
          </SelectTrigger>
          <SelectContent>
            {companies.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {!companyId ? (
        <EmptyState icon={Building2} title="Choose a company to see who can be impersonated" />
      ) : (
        <Card className="overflow-hidden">
          <AsyncBoundary
            state={usersState}
            isEmpty={(d) => d.length === 0}
            empty={{ icon: Users2, title: "No users at this company" }}
          >
            {(users) => (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">User</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <PermissionGate permission="platform.impersonate">
                      <TableHead className="pr-4 text-right">Actions</TableHead>
                    </PermissionGate>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => (
                    <TableRow key={u.id} data-testid={`impersonate-row-${u.email}`}>
                      <TableCell className="pl-4">
                        <span className="flex items-center gap-3">
                          <Avatar>
                            <AvatarFallback>{initials(u.fullName)}</AvatarFallback>
                          </Avatar>
                          <span className="min-w-0">
                            <span className="block font-medium text-foreground">{u.fullName}</span>
                            <span className="block text-caption text-muted-foreground">{u.email}</span>
                          </span>
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{u.roleName || u.roleCode}</TableCell>
                      <TableCell className="text-muted-foreground">{u.status}</TableCell>
                      <PermissionGate permission="platform.impersonate">
                        <TableCell className="pr-4">
                          <div className="flex justify-end">
                            <ImpersonateButton user={u} />
                          </div>
                        </TableCell>
                      </PermissionGate>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </AsyncBoundary>
        </Card>
      )}
    </div>
  );
}

function ImpersonateButton({ user }: { user: PlatformUserRow }) {
  const router = useRouter();
  const session = useSession();
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");

  const start = React.useCallback(
    (input: { targetUserId: Id; reason: string }) => authApi.startImpersonation(input.targetUserId, input.reason),
    [],
  );
  const impersonate = useApiMutation(start, {
    onSuccess: () => {
      session.refresh();
      setOpen(false);
      router.push("/dashboard");
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setReason("");
          impersonate.reset();
        }
      }}
    >
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        data-testid={`impersonate-${user.email}`}
      >
        <LogIn />
        Impersonate
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Impersonate {user.fullName}?</DialogTitle>
          <DialogDescription>
            You&apos;ll be signed in as {user.fullName} ({user.email}) for 30 minutes. The session
            cannot be refreshed, and every action you take is logged against your platform admin
            account, not theirs — a reason is required.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3.5">
          <div className="space-y-1.5">
            <Label htmlFor="imp-reason">Reason</Label>
            <Textarea
              id="imp-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Investigating a support ticket about a missing GRN"
              autoFocus
            />
          </div>
          <FormError message={impersonate.error} fieldErrors={impersonate.fieldErrors} />
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={impersonate.isPending}>
            Cancel
          </Button>
          <Button
            disabled={!reason.trim() || impersonate.isPending}
            data-testid="impersonate-confirm"
            onClick={() => impersonate.run({ targetUserId: user.id, reason })}
          >
            {impersonate.isPending ? "Starting..." : "Start Impersonating"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* -------------------------------------------------------------- Activity */

function PlatformActivityTab({ version }: { version: number }) {
  // `version` is part of the query key rather than an effect: onboarding or
  // suspending a company writes an audit row, so the feed has to re-read,
  // and refetching from an effect would race the first load.
  const state = usePlatformActivity(100, undefined, version);

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-border px-4 py-3">
        <p className="text-section text-foreground">Recent Activity</p>
        <p className="mt-0.5 text-caption text-muted-foreground">
          Every create, edit, status change and delete across every company, newest first
        </p>
      </div>
      <AsyncBoundary
        state={state}
        isEmpty={(d) => d.length === 0}
        empty={{ icon: ShieldAlert, title: "No platform activity recorded yet" }}
      >
        {(rows) => (
          <AuditEventList
            // The feed spans tenants, so each row is labelled with the
            // company it happened in — otherwise "Supplier updated" twice in
            // a row says nothing about who.
            events={rows.map((r) => ({
              ...r,
              entityLabel: [r.companyName, r.entityLabel].filter(Boolean).join(" · "),
            })) as unknown as AuditLog[]}
            emptyLabel="No platform activity recorded yet."
            showEntity
          />
        )}
      </AsyncBoundary>
    </Card>
  );
}
