"use client";

import * as React from "react";
import Link from "next/link";
import {
  BadgeCheck,
  Building2,
  CalendarClock,
  Check,
  ChevronDown,
  Clock,
  History,
  Home,
  Mail,
  Phone,
  RotateCcw,
  Save,
  ShieldCheck,
  UserRound,
  Warehouse,
} from "lucide-react";

import { ChangePasswordCard } from "@/components/admin/change-password-card";
import { FormError, LoadingCard } from "@/components/common/async-state";
import { SectionCard } from "@/components/common/section-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdateMyProfile } from "@/hooks/use-admin";
import { useApiQuery } from "@/hooks/use-api";
import { useAuditTrail } from "@/hooks/use-ops";
import { useMyCompanies, usePermission, useSession } from "@/hooks/use-session";
import { catalogApi } from "@/lib/api";
import { PERMISSION_GROUPS, permissionLabel } from "@/lib/domain/permissions";
import { formatDateTime, formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PermissionCode, SessionUser } from "@/types";

/**
 * My Profile — the signed-in person's own account.
 *
 * Everything here is read from `GET /auth/me` (via the session) and the
 * access token's permission claims; the only write is `PATCH /auth/me`, which
 * edits name and phone. Email, role, status and godown access belong to
 * whoever holds `user.manage` and are shown read-only, with a pointer to who
 * can change them.
 */
export function ProfileScreen() {
  const { user, impersonation, isLoading } = useSession();

  if (!user) {
    return (
      <div className="mx-auto w-full max-w-6xl">
        <LoadingCard />
        {!isLoading && <p className="p-4 text-body text-muted-foreground">You are not signed in.</p>}
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5" data-testid="profile-screen">
      <ProfileHero user={user} />

      {impersonation && (
        <Alert>
          <ShieldCheck />
          <AlertDescription>
            You are viewing this profile while impersonating. It is read-only — the person&apos;s own details and
            password can only be changed by them.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-5 lg:col-span-3">
          <PersonalDetailsCard user={user} readOnly={!!impersonation} />
          {!impersonation && <ChangePasswordCard />}
          <ActivityCard userId={user.id} />
        </div>
        <div className="space-y-5 lg:col-span-2">
          <AccessCard user={user} />
          {!user.isPlatformAdmin && <CompaniesCard />}
          <PermissionsCard permissions={user.permissions} />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Hero */

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function ProfileHero({ user }: { user: SessionUser }) {
  const godownLabel = user.godownScope.all
    ? "All godowns"
    : `${user.godownScope.godownIds.length} godown${user.godownScope.godownIds.length === 1 ? "" : "s"}`;

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div
        className="relative h-28 sm:h-32"
        style={{ background: "linear-gradient(120deg, var(--primary) 0%, var(--chart-5) 100%)" }}
        aria-hidden="true"
      >
        <div
          className="absolute inset-0 opacity-20"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 30%, white 0 1.5px, transparent 2px), radial-gradient(circle at 70% 60%, white 0 1px, transparent 1.5px)",
            backgroundSize: "36px 36px, 24px 24px",
          }}
        />
      </div>

      <div className="relative z-10 px-5 pb-5">
        <div className="-mt-12 flex flex-col gap-4 sm:-mt-16 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div
              className="flex size-24 shrink-0 items-center justify-center rounded-2xl border-4 border-card text-3xl font-semibold text-primary-foreground shadow-md sm:size-32"
              style={{ background: "linear-gradient(135deg, var(--primary), var(--chart-5))" }}
              aria-hidden="true"
            >
              {initialsOf(user.fullName)}
            </div>
            <div className="min-w-0 sm:pb-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-display truncate text-foreground" data-testid="profile-name">
                  {user.fullName}
                </h1>
                <StatusPill status={user.status} />
              </div>
              <p className="mt-0.5 flex items-center gap-1.5 text-body text-muted-foreground">
                <Mail className="size-3.5" />
                <span className="truncate">{user.email}</span>
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 sm:pb-1">
            <Badge variant="default" className="gap-1">
              <ShieldCheck className="size-3" />
              {user.isPlatformAdmin ? "Platform Admin" : user.roleName}
            </Badge>
            {!user.isPlatformAdmin && (
              <Badge variant="outline" className="gap-1">
                <Building2 className="size-3" />
                {user.companyName}
              </Badge>
            )}
          </div>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
          <HeroStat icon={ShieldCheck} label="Role" value={user.isPlatformAdmin ? "Platform Admin" : user.roleName} />
          <HeroStat icon={Warehouse} label="Godown access" value={user.isPlatformAdmin ? "Platform" : godownLabel} />
          <HeroStat icon={BadgeCheck} label="Permissions" value={String(user.permissions.length)} />
          <HeroStat
            icon={Clock}
            label="Last sign-in"
            value={user.lastActiveAt ? formatRelativeTime(user.lastActiveAt) : "—"}
            title={user.lastActiveAt ? formatDateTime(user.lastActiveAt) : undefined}
          />
        </dl>
      </div>
    </section>
  );
}

function HeroStat({
  icon: Icon,
  label,
  value,
  title,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  title?: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/40 px-3 py-2.5" title={title}>
      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary-subtle text-primary-subtle-foreground">
        <Icon className="size-4" />
      </span>
      <div className="min-w-0">
        <dt className="text-caption text-muted-foreground">{label}</dt>
        <dd className="truncate text-[14px] font-semibold text-foreground">{value}</dd>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const active = status === "active";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium capitalize",
        active ? "bg-success-subtle text-success-subtle-foreground" : "bg-warning-subtle text-warning-subtle-foreground",
      )}
    >
      <span className={cn("size-1.5 rounded-full", active ? "bg-success" : "bg-warning")} />
      {status}
    </span>
  );
}

/* ------------------------------------------------------ Personal details */

function PersonalDetailsCard({ user, readOnly }: { user: SessionUser; readOnly: boolean }) {
  const { refresh } = useSession();
  const [fullName, setFullName] = React.useState(user.fullName);
  const [phone, setPhone] = React.useState(user.phone ?? "");
  const [savedAt, setSavedAt] = React.useState<number | null>(null);

  // Re-seed when the session changes underneath (a save, a company switch).
  React.useEffect(() => {
    setFullName(user.fullName);
    setPhone(user.phone ?? "");
  }, [user.fullName, user.phone]);

  const save = useUpdateMyProfile(() => {
    setSavedAt(Date.now());
    refresh();
  });

  const dirty = fullName.trim() !== user.fullName || phone.trim() !== (user.phone ?? "");
  const nameError = fullName.trim() === "" ? "Your name can't be empty." : null;
  const phoneError = phone && !/^[0-9+\-() ]*$/.test(phone) ? "Digits, spaces, +, - and brackets only." : null;
  const canSave = dirty && !nameError && !phoneError && !save.isPending && !readOnly;

  React.useEffect(() => {
    if (!savedAt) return;
    const t = window.setTimeout(() => setSavedAt(null), 4000);
    return () => window.clearTimeout(t);
  }, [savedAt]);

  return (
    <SectionCard
      title="Personal Details"
      description="How you appear to your team — on approvals, receipts and the audit trail"
      action={
        savedAt ? (
          <span className="inline-flex items-center gap-1 text-caption font-medium text-success-subtle-foreground" role="status">
            <Check className="size-3.5" /> Saved
          </span>
        ) : undefined
      }
    >
      <form
        className="space-y-4 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSave) void save.run({ fullName, phone });
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="pf-name">Full name</Label>
            <div className="relative">
              <UserRound className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="pf-name"
                className="pl-9"
                value={fullName}
                maxLength={300}
                disabled={readOnly}
                onChange={(e) => setFullName(e.target.value)}
                aria-invalid={!!(nameError || save.fieldErrors.full_name)}
              />
            </div>
            {(nameError || save.fieldErrors.full_name) && (
              <p className="text-caption text-destructive">{nameError ?? save.fieldErrors.full_name}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pf-phone">Phone</Label>
            <div className="relative">
              <Phone className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="pf-phone"
                className="pl-9"
                type="tel"
                inputMode="tel"
                placeholder="+91 98765 43210"
                value={phone}
                maxLength={20}
                disabled={readOnly}
                onChange={(e) => setPhone(e.target.value)}
                aria-invalid={!!(phoneError || save.fieldErrors.phone)}
              />
            </div>
            {(phoneError || save.fieldErrors.phone) && (
              <p className="text-caption text-destructive">{phoneError ?? save.fieldErrors.phone}</p>
            )}
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="pf-email">Email</Label>
          <div className="relative">
            <Mail className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input id="pf-email" className="pl-9" value={user.email} readOnly disabled />
          </div>
          <p className="text-caption text-muted-foreground">
            Your email is your sign-in. Ask a company Owner or Admin to change it.
          </p>
        </div>

        <FormError message={save.error} fieldErrors={save.fieldErrors} />

        {!readOnly && (
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
            {dirty && <span className="mr-auto text-caption text-muted-foreground">You have unsaved changes</span>}
            <Button
              type="button"
              variant="outline"
              disabled={!dirty || save.isPending}
              onClick={() => {
                setFullName(user.fullName);
                setPhone(user.phone ?? "");
                save.reset();
              }}
            >
              <RotateCcw />
              Discard
            </Button>
            <Button type="submit" disabled={!canSave}>
              <Save />
              {save.isPending ? "Saving..." : "Save changes"}
            </Button>
          </div>
        )}
      </form>
    </SectionCard>
  );
}

/* ---------------------------------------------------------------- Access */

function AccessCard({ user }: { user: SessionUser }) {
  const canSeeGodowns = usePermission("godown.view");
  const godowns = useApiQuery(["godowns"], () => catalogApi.listGodowns(), {
    enabled: canSeeGodowns && !user.godownScope.all,
  });
  const scopedNames = (godowns.data ?? [])
    .filter((g) => user.godownScope.godownIds.includes(g.id))
    .map((g) => g.name);

  return (
    <SectionCard title="Access" description="Set by your company's Owner or Admin">
      <dl className="divide-y divide-border">
        <AccessRow icon={ShieldCheck} label="Role">
          {user.isPlatformAdmin ? "Platform Admin" : user.roleName}
        </AccessRow>
        {!user.isPlatformAdmin && (
          <AccessRow icon={Building2} label="Acting in">
            {user.companyName}
            {user.homeCompanyId && user.homeCompanyId !== user.companyId && (
              <span className="ml-1.5 text-caption text-muted-foreground">(switched from home)</span>
            )}
          </AccessRow>
        )}
        {!user.isPlatformAdmin && (
          <AccessRow icon={Warehouse} label="Godowns">
            {user.godownScope.all ? (
              "All godowns"
            ) : scopedNames.length ? (
              <span className="flex flex-wrap justify-end gap-1">
                {scopedNames.map((n) => (
                  <Badge key={n} variant="neutral">
                    {n}
                  </Badge>
                ))}
              </span>
            ) : (
              `${user.godownScope.godownIds.length} assigned`
            )}
          </AccessRow>
        )}
        <AccessRow icon={CalendarClock} label="Last sign-in">
          {user.lastActiveAt ? formatDateTime(user.lastActiveAt) : "—"}
        </AccessRow>
      </dl>
    </SectionCard>
  );
}

function AccessRow({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-4 py-3">
      <dt className="flex shrink-0 items-center gap-2 text-caption text-muted-foreground">
        <Icon className="size-4" />
        {label}
      </dt>
      <dd className="min-w-0 text-right text-[13.5px] font-medium text-foreground">{children}</dd>
    </div>
  );
}

/* ------------------------------------------------------------- Companies */

function CompaniesCard() {
  const companies = useMyCompanies();
  const rows = companies.data ?? [];

  return (
    <SectionCard
      title="Companies"
      description={rows.length > 1 ? "Switch between them from the header menu" : "Where your account belongs"}
    >
      {companies.isLoading && !companies.data ? (
        <LoadingCard />
      ) : rows.length === 0 ? (
        <p className="p-4 text-caption text-muted-foreground">No company memberships.</p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((c) => (
            <li key={c.companyId} className="flex items-center gap-3 px-4 py-3">
              <span
                className={cn(
                  "flex size-9 shrink-0 items-center justify-center rounded-md text-[13px] font-semibold",
                  c.isCurrent ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                )}
              >
                {initialsOf(c.companyName)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5 truncate text-[13.5px] font-medium text-foreground">
                  {c.companyName}
                  {c.isHome && <Home className="size-3.5 text-muted-foreground" aria-label="Home company" />}
                </p>
                <p className="text-caption text-muted-foreground">
                  {c.roleName}
                  {c.companyStatus !== "active" && " · Suspended"}
                </p>
              </div>
              {c.isCurrent && <Badge variant="success">Current</Badge>}
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

/* ----------------------------------------------------------- Permissions */

function PermissionsCard({ permissions }: { permissions: PermissionCode[] }) {
  const [open, setOpen] = React.useState<string | null>(null);
  const held = new Set(permissions);
  const groups = PERMISSION_GROUPS.map((g) => ({
    ...g,
    granted: g.permissions.filter((p) => held.has(p)),
  })).filter((g) => g.granted.length > 0);

  return (
    <SectionCard
      title="What you can do"
      description={`${permissions.length} permission${permissions.length === 1 ? "" : "s"} from your role`}
    >
      {groups.length === 0 ? (
        <p className="p-4 text-caption text-muted-foreground">Your role grants no permissions in this company.</p>
      ) : (
        <ul className="divide-y divide-border">
          {groups.map((g) => {
            const pct = Math.round((g.granted.length / g.permissions.length) * 100);
            const isOpen = open === g.label;
            return (
              <li key={g.label}>
                <button
                  type="button"
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-muted/50"
                  aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? null : g.label)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13.5px] font-medium text-foreground">{g.label}</span>
                      <span className="shrink-0 text-caption text-muted-foreground tabular-nums">
                        {g.granted.length}/{g.permissions.length}
                      </span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn("h-full rounded-full", pct === 100 ? "bg-success" : "bg-primary")}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                  <ChevronDown
                    className={cn("size-4 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-180")}
                  />
                </button>
                {isOpen && (
                  <ul className="flex flex-wrap gap-1.5 px-4 pb-3">
                    {g.granted.map((p) => (
                      <li key={p}>
                        <Badge variant="neutral" className="gap-1 capitalize">
                          <Check className="size-3" />
                          {permissionLabel(p)}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </SectionCard>
  );
}

/* -------------------------------------------------------------- Activity */

const ACTION_TEXT: Record<string, string> = {
  logged_in: "Signed in",
  logged_out: "Signed out",
  login_failed: "Failed sign-in attempt",
  updated: "Profile updated",
  password_changed: "Password changed",
  password_reset: "Password reset",
};

function ActivityCard({ userId }: { userId: string }) {
  const canView = usePermission("audit.view");
  const trail = useAuditTrail(canView ? "user" : undefined, canView ? userId : undefined);
  if (!canView) return null;
  const rows = (trail.data ?? []).slice(0, 8);

  return (
    <SectionCard
      title="Recent account activity"
      description="Sign-ins and changes to your account"
      action={
        <Button variant="ghost" size="sm" asChild>
          <Link href="/audit">
            <History />
            Audit trail
          </Link>
        </Button>
      }
    >
      {trail.isLoading && !trail.data ? (
        <LoadingCard />
      ) : rows.length === 0 ? (
        <p className="p-4 text-caption text-muted-foreground">No recorded activity yet.</p>
      ) : (
        <ol className="relative space-y-0 p-4">
          {rows.map((r, i) => (
            <li key={r.id} className="relative flex gap-3 pb-4 last:pb-0">
              {i < rows.length - 1 && (
                <span className="absolute top-6 left-[11px] h-[calc(100%-1rem)] w-px bg-border" aria-hidden="true" />
              )}
              <span
                className={cn(
                  "relative z-10 mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full",
                  (r.action as string) === "login_failed"
                    ? "bg-warning-subtle text-warning-subtle-foreground"
                    : "bg-primary-subtle text-primary-subtle-foreground",
                )}
              >
                <span className="size-1.5 rounded-full bg-current" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[13.5px] font-medium text-foreground">
                  {r.description && r.action === "updated" ? r.description : ACTION_TEXT[r.action] ?? r.action.replace(/_/g, " ")}
                </p>
                <p className="text-caption text-muted-foreground" title={formatDateTime(r.createdAt)}>
                  {formatRelativeTime(r.createdAt)}
                  {r.actorName && r.actorUserId !== userId && ` · by ${r.actorName}`}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </SectionCard>
  );
}
