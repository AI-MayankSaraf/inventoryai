/**
 * Users, roles, invitations, godowns, company settings and the platform
 * console.
 *
 * Everything tenant-level here talks to the real FastAPI backend: users,
 * invitations, roles and permissions (read-only — the schema fixes the seven
 * built-in roles), godowns with their usage and deactivation guard, company
 * profile and settings, and the live document-numbering series.
 *
 * The platform console (`listCompanies`, `onboardCompany`,
 * `setCompanyStatus`, `listPlatformUsers`, `listPlatformActivity`) is real
 * too, on `/platform/*` — a separate auth model, not a separate data source:
 * those endpoints answer only to a platform admin's token.
 */

import { indexById, query } from "@/mock/repository";
import type {
  Company,
  CompanySettings,
  DocumentSequence,
  Godown,
  GodownScope,
  Id,
  Invitation,
  InvitationStatus,
  ListParams,
  ListResponse,
  PermissionCode,
  Role,
  RoleCode,
  User,
} from "@/types";
import { actorId, actorName } from "./audit";
import { httpDelete, httpGet, httpPatch, httpPost, httpPut, notFound, reject, validationFailed } from "./client";

/* --------------------------------------------------------- Backend shapes */

/** `/users` — see the wiring brief's Users section. */
interface UserOut {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role_id: string;
  role_code: string;
  status: string;
  has_all_godowns: boolean;
  godown_scope: string;
  godown_ids: string[];
  last_login_at: string | null;
  created_at: string;
}

/** `GET /invitations` — the full row. */
interface InvitationOut {
  id: string;
  email: string;
  full_name: string;
  role_code: string;
  godown_scope: string;
  status: string;
  invited_at: string;
  expires_at: string;
  resend_count: number;
}

/** `POST /users/invite` and `POST /invitations/{id}/resend` — a compact
 * echo, not the full row above. */
interface InviteActionOut {
  id: string;
  email: string;
  full_name: string;
  role_code: string;
  expires_at: string;
  invitation_token: string | null;
}

/** `/catalog/godowns` — same shape Assignment A's `catalog.api.ts` wires. */
interface GodownOut {
  id: string;
  name: string;
  code: string | null;
  city: string;
  state_code: string;
  address: string | null;
  gstin: string | null;
  is_default: boolean;
  is_active: boolean;
  incharge_user_id: string | null;
  capacity_value: number | null;
  capacity_uom_id: string | null;
}

interface CompanyProfileOut {
  id: string;
  name: string;
  legal_name: string | null;
  gstin: string | null;
  pan: string | null;
  state_code: string;
  state_name: string;
  // Both nullable server-side (`CompanyProfileOut`). This interface used to
  // declare them as plain strings, so a company with no address on file
  // handed `null` straight to a controlled <input> on the Settings screen.
  city: string | null;
  address_line1: string | null;
  address_line2: string | null;
  pincode: string | null;
  email: string | null;
  phone: string | null;
  plan: string;
  status: string;
  onboarded_on: string;
}

interface CompanySettingsOut {
  company_id: string;
  currency_code: string;
  default_gst_rate: number;
  rounding_mode: string;
  financial_year_start_month: number;
  default_godown_id: string | null;
  ai_auto_process: boolean;
  ai_review_confidence_threshold: number;
  ai_suggest_while_typing: boolean;
  ai_never_autoapprove_financials: boolean;
  low_stock_threshold_mode: string;
  alert_email_critical: boolean;
  alert_daily_low_stock_digest: boolean;
  alert_po_delay_notify: boolean;
  po_delay_grace_days: number;
  allow_grn_excess_receipt: boolean;
  grn_excess_tolerance_pct: number;
  require_po_approval_above: number | null;
  require_maker_checker: boolean;
  allow_negative_stock: boolean;
  allow_nonstandard_gst: boolean;
  inventory_locked_through: string | null;
  variance_price_tolerance_pct: number;
  variance_amount_tolerance: number;
  comparison_weights: Record<string, number>;
}

/* -------------------------------------------------- snake_case -> camelCase */

function toUser(u: UserOut): User {
  return {
    id: u.id,
    // Not returned by this company-scoped endpoint (implicit from the
    // caller's own token) — nothing in the current UI reads it here.
    companyId: null,
    email: u.email,
    fullName: u.full_name,
    phone: u.phone ?? undefined,
    roleId: u.role_id,
    roleCode: u.role_code as RoleCode,
    status: u.status as User["status"],
    isPlatformAdmin: false,
    godownScope: { all: u.has_all_godowns, godownIds: u.godown_ids ?? [] },
    lastActiveAt: u.last_login_at ?? undefined,
    deletedAt: null,
  };
}

function toInvitation(o: InvitationOut): Invitation {
  return {
    id: o.id,
    email: o.email,
    fullName: o.full_name,
    // No backend field for the invite's mock role id — the users-screen
    // table already falls back to `roleCode` for display when `roleId`
    // doesn't match a known role, so this is a safe simplification.
    roleId: "",
    roleCode: o.role_code as RoleCode,
    // The list endpoint returns `godown_scope` ("all"|"specific") but not
    // the actual `godown_ids` — known gap, so a "specific" invite shows an
    // empty godown list rather than the real one.
    godownScope: { all: o.godown_scope === "all", godownIds: [] },
    invitedBy: "",
    invitedByName: "",
    invitedAt: o.invited_at,
    expiresAt: o.expires_at,
    resendCount: o.resend_count,
    status: o.status as InvitationStatus,
  };
}

function capitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s;
}

function toCompany(o: CompanyProfileOut): Company {
  return {
    id: o.id,
    name: o.name,
    legalName: o.legal_name ?? undefined,
    gstin: o.gstin,
    pan: o.pan,
    stateCode: o.state_code,
    stateName: o.state_name,
    city: o.city ?? "",
    addressLine1: o.address_line1 ?? "",
    addressLine2: o.address_line2 ?? undefined,
    pincode: o.pincode ?? undefined,
    email: o.email ?? undefined,
    phone: o.phone ?? undefined,
    // The backend's plan/status enums are assumed lower-case; the frontend
    // type expects the title-cased strings the mock seeded. Capitalising
    // defensively also leaves an already-capitalised value untouched.
    plan: capitalize(o.plan) as Company["plan"],
    status: o.status as Company["status"],
    // No backend field for suspension metadata or the owning account's
    // email on this endpoint — known gap, not rendered by the profile
    // screen today.
    suspendedAt: null,
    suspendedReason: null,
    onboardedOn: o.onboarded_on,
    ownerEmail: "",
  };
}

/** The `numbering` block on CompanySettings is a convenience view of the
 * real `document_sequences` rows. It is kept in the settings shape because
 * several screens read `settings.numbering.po.prefix` directly, but the
 * values are the allocator's, not a separate stored setting. */
async function realNumbering(): Promise<CompanySettings["numbering"]> {
  const def = (prefix: string) => ({ prefix, padding: 5 });
  const fallback: CompanySettings["numbering"] = {
    rfq: def("RFQ-"),
    po: def("PO-"),
    grn: def("GRN-"),
    proforma: def("PI-"),
    invoice: def("SI-"),
    transfer: def("TRF-"),
    return: def("PR-"),
    adjustment: def("ADJ-"),
  };

  // The current financial year's series win. A prefix is unique per
  // (doc_type, financial_year), so an older year's row is history, not the
  // prefix the next document will get.
  try {
    const rows = await listDocumentSequences();
    const latestYear = rows.reduce<string>((y, r) => (r.financialYear > y ? r.financialYear : y), "");
    for (const row of rows) {
      if (row.financialYear !== latestYear) continue;
      const key = row.docType as keyof CompanySettings["numbering"];
      if (key in fallback) fallback[key] = { prefix: row.prefix, padding: row.padding };
    }
  } catch {
    // A numbering panel showing defaults is better than a Settings screen
    // that will not load at all.
  }
  return fallback;
}

async function toCompanySettings(o: CompanySettingsOut): Promise<CompanySettings> {
  return {
    id: o.company_id,
    companyId: o.company_id,
    currencyCode: o.currency_code,
    defaultGstRate: o.default_gst_rate,
    roundingMode: o.rounding_mode as CompanySettings["roundingMode"],
    financialYearStartMonth: o.financial_year_start_month,
    defaultGodownId: o.default_godown_id,
    aiAutoProcess: o.ai_auto_process,
    aiReviewConfidenceThreshold: o.ai_review_confidence_threshold,
    aiSuggestWhileTyping: o.ai_suggest_while_typing,
    aiNeverAutoApproveFinancials: true,
    lowStockThresholdMode: o.low_stock_threshold_mode as CompanySettings["lowStockThresholdMode"],
    alertEmailCritical: o.alert_email_critical,
    alertDailyLowStockDigest: o.alert_daily_low_stock_digest,
    alertPoDelayNotify: o.alert_po_delay_notify,
    poDelayGraceDays: o.po_delay_grace_days,
    allowNegativeStock: o.allow_negative_stock,
    inventoryLockedThrough: o.inventory_locked_through,
    allowGrnExcessReceipt: o.allow_grn_excess_receipt,
    grnExcessTolerancePct: o.grn_excess_tolerance_pct,
    requirePoApprovalAbove: o.require_po_approval_above,
    requireMakerChecker: o.require_maker_checker,
    variancePriceTolerancePct: o.variance_price_tolerance_pct,
    varianceAmountTolerance: o.variance_amount_tolerance,
    numbering: await realNumbering(),
  };
}

function toGodown(g: GodownOut, inchargeName = ""): Godown {
  return {
    id: g.id,
    name: g.name,
    code: g.code ?? undefined,
    city: g.city,
    stateCode: g.state_code,
    address: g.address ?? undefined,
    gstin: g.gstin,
    inchargeUserId: g.incharge_user_id,
    // The name comes from `/company/godown-usage` (one query for the whole
    // list); a single godown read doesn't carry it.
    inchargeName,
    capacityValue: g.capacity_value ?? undefined,
    capacityUomId: g.capacity_uom_id,
    isDefault: g.is_default,
    isActive: g.is_active,
    deletedAt: null,
    createdAt: "",
    updatedAt: "",
  };
}

/* ----------------------------------------------------------------- Users */

export interface UserListRow extends User {
  roleName: string;
  godownNames: string[];
  companyName: string;
}

export async function listUsers(params: ListParams = {}): Promise<ListResponse<UserListRow>> {
  // No free-text search/sort on the backend (rule 7 of the wiring brief) —
  // fetch a generously large page and let `query()` do the rest client-side,
  // exactly like the mock did.
  const [usersOut, godowns, roles] = await Promise.all([
    httpGet<UserOut[]>("/users", { limit: 500 }),
    httpGet<GodownOut[]>("/catalog/godowns", { limit: 500 }),
    listRoles(), // stays mock — just the 6 fixed roles, used here to label role_code
  ]);
  const godownsById = indexById(godowns);
  const roleNameByCode = new Map(roles.map((r) => [r.code, r.name]));
  const rows: UserListRow[] = usersOut.map((u) => {
    const user = toUser(u);
    return {
      ...user,
      roleName: roleNameByCode.get(user.roleCode) ?? user.roleCode,
      godownNames: user.godownScope.all
        ? ["All godowns"]
        : user.godownScope.godownIds.map((id) => godownsById.get(id)?.name ?? "").filter(Boolean),
      // No per-user company field on this company-scoped endpoint, and the
      // Users screen doesn't render it — safe simplification.
      companyName: "",
    };
  });
  return query(rows as unknown as Record<string, unknown>[], params, {
    searchFields: ["fullName", "email", "roleName"],
    facetFields: ["status", "roleCode"],
    defaultSort: "fullName",
  }) as unknown as ListResponse<UserListRow>;
}

export async function listInvitations(): Promise<Invitation[]> {
  const rows = await httpGet<InvitationOut[]>("/invitations", { limit: 500 });
  return rows.filter((i) => i.status === "pending").map(toInvitation);
}

export interface InviteInput {
  email: string;
  fullName: string;
  roleId: Id;
  godownScope: GodownScope;
}

/** The accept link the invitation email carries. The server stores only a
 * hash of the token, so this can be built only from an invite/resend response,
 * and the backend includes the raw token there only in development. */
function inviteLinkFor(token: string | null): string | undefined {
  if (!token || typeof window === "undefined") return undefined;
  return `${window.location.origin}/accept-invitation?token=${encodeURIComponent(token)}`;
}

/** The create/resend responses are a compact echo, not the full
 * `GET /invitations` row — re-fetch the list to get the canonical row back,
 * falling back to a synthesised one (from the compact response + what we
 * already know) if it's somehow not there yet. */
async function fetchInvitationOrSynthesize(
  id: Id,
  fallback: { email: string; fullName: string; roleId?: Id; roleCode: RoleCode; godownScope?: GodownScope; expiresAt: string; resendCount?: number },
): Promise<Invitation> {
  try {
    const list = await httpGet<InvitationOut[]>("/invitations", { limit: 500 });
    const match = list.find((i) => i.id === id);
    if (match) return toInvitation(match);
  } catch {
    /* fall through to the synthesised version below */
  }
  return {
    id,
    email: fallback.email,
    fullName: fallback.fullName,
    roleId: fallback.roleId ?? "",
    roleCode: fallback.roleCode,
    godownScope: fallback.godownScope ?? { all: true, godownIds: [] },
    invitedBy: actorId(),
    invitedByName: actorName(),
    invitedAt: new Date().toISOString(),
    expiresAt: fallback.expiresAt,
    resendCount: fallback.resendCount ?? 0,
    status: "pending",
  };
}

export async function inviteUser(input: InviteInput): Promise<Invitation> {
  const errors: { field: string; message: string }[] = [];
  if (!input.fullName.trim()) errors.push({ field: "fullName", message: "Enter a name." });
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(input.email)) {
    errors.push({ field: "email", message: "Enter a valid email address." });
  }
  if (!input.roleId) errors.push({ field: "roleId", message: "Choose a role." });
  if (!input.godownScope.all && input.godownScope.godownIds.length === 0) {
    errors.push({ field: "godownScope", message: "Choose at least one godown, or grant access to all." });
  }
  // The "email already has access" / "invitation already pending" clash
  // checks that used to run against the mock `users`/`invitations` tables
  // are dropped (same judgment call as catalog.api.ts's SKU-uniqueness
  // check): those tables no longer reflect what actually exists. The
  // backend enforces this itself and returns a 422 `VALIDATION_FAILED`.
  if (errors.length) validationFailed(errors);

  const role = await roleById(input.roleId);
  if (!role) notFound("Role");

  const created = await httpPost<InviteActionOut>("/users/invite", {
    email: input.email.trim().toLowerCase(),
    full_name: input.fullName.trim(),
    role_code: role.code,
    godown_scope: input.godownScope.all ? "all" : "specific",
    godown_ids: input.godownScope.all ? undefined : input.godownScope.godownIds,
  });

  const invitation = await fetchInvitationOrSynthesize(created.id, {
    email: created.email,
    fullName: created.full_name,
    roleId: input.roleId,
    roleCode: created.role_code as RoleCode,
    godownScope: input.godownScope,
    expiresAt: created.expires_at,
    resendCount: 0,
  });
  return { ...invitation, inviteLink: inviteLinkFor(created.invitation_token) };
}

export async function resendInvitation(invitationId: Id): Promise<Invitation> {
  const out = await httpPost<InviteActionOut>(`/invitations/${invitationId}/resend`);
  const invitation = await fetchInvitationOrSynthesize(invitationId, {
    email: out.email,
    fullName: out.full_name,
    roleCode: out.role_code as RoleCode,
    expiresAt: out.expires_at,
  });
  return { ...invitation, inviteLink: inviteLinkFor(out.invitation_token) };
}

export async function revokeInvitation(invitationId: Id): Promise<void> {
  await httpDelete(`/invitations/${invitationId}`);
}

export async function updateUserAccess(
  userId: Id,
  patch: { roleId?: Id; godownScope?: GodownScope; status?: User["status"] },
): Promise<User> {
  // The "last active owner cannot be demoted/deactivated" guard (BR-AUTH-04)
  // used to run against the mock `users` table — dropped here, same
  // reasoning as elsewhere: that table no longer reflects who's really an
  // active owner once users are real. The backend is expected to enforce
  // this itself and return a 422/409.
  const body: Record<string, unknown> = {};
  if (patch.roleId) {
    const role = await roleById(patch.roleId);
    if (!role) notFound("Role");
    body.role_code = role.code;
  }
  if (patch.godownScope) {
    body.godown_scope = patch.godownScope.all ? "all" : "specific";
    body.godown_ids = patch.godownScope.all ? [] : patch.godownScope.godownIds;
  }
  if (patch.status) body.status = patch.status;

  const out = await httpPatch<UserOut>(`/users/${userId}`, body);
  return toUser(out);
}

export async function removeUser(userId: Id): Promise<void> {
  // Same BR-AUTH-04 "last owner" guard dropped here as `updateUserAccess`
  // above, for the same reason.
  await httpDelete(`/users/${userId}`);
}

/* ----------------------------------------------------------------- Roles */

/** `GET /roles` — mirrors `RoleOut` in `app/modules/auth/users_schemas.py`. */
interface RoleOut {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
  user_count: number;
}

/** `GET /permissions` — the global catalogue. */
interface PermissionOut {
  code: string;
  module: string;
  description: string | null;
}

export interface RoleWithUsage extends Role {
  userCount: number;
}

function toRole(r: RoleOut): RoleWithUsage {
  return {
    id: r.id,
    code: r.code as RoleCode,
    name: r.name,
    description: r.description ?? undefined,
    isSystem: r.is_system,
    permissions: r.permissions as PermissionCode[],
    userCount: r.user_count,
  };
}

/**
 * The seven built-ins are read-only; a company may define roles of its own
 * alongside them (`is_system: false`), within the limits of what the person
 * defining it already holds — the server refuses anything wider with
 * `ROLE_ESCALATION`.
 *
 * `super_admin` is filtered out server-side: it is a platform role with no
 * tenant-data permissions, so it is not assignable here.
 */
export async function listRoles(): Promise<RoleWithUsage[]> {
  return (await httpGet<RoleOut[]>("/roles")).map(toRole);
}

export async function getRole(roleId: Id): Promise<Role> {
  return toRole(await httpGet<RoleOut>(`/roles/${roleId}`));
}

/**
 * Resolve a role id to its role, for the forms that hold an id but must send
 * a `role_code`.
 *
 * This has to hit the real catalogue: the ids in those forms come from
 * `GET /roles`. Cached, and the cache is dropped whenever a role is created,
 * edited or deleted — custom roles mean the list is no longer fixed.
 */
let roleCache: Promise<RoleWithUsage[]> | null = null;

async function roleById(roleId: Id): Promise<RoleWithUsage | undefined> {
  roleCache ??= listRoles();
  try {
    return (await roleCache).find((r) => r.id === roleId);
  } catch {
    roleCache = null;
    throw new Error("Could not load roles.");
  }
}

/** The permission catalogue, for labelling and for grouping anything the
 *  frontend's own `PERMISSION_GROUPS` doesn't know about yet. */
export async function listPermissions(): Promise<
  { code: PermissionCode; module: string; description?: string }[]
> {
  return (await httpGet<PermissionOut[]>("/permissions")).map((p) => ({
    code: p.code as PermissionCode,
    module: p.module,
    description: p.description ?? undefined,
  }));
}

/* --------------------------------------------------------------- Godowns */

/** `GET /company/godown-usage` — mirrors `GodownUsageOut`. */
interface GodownUsageOut {
  godown_id: string;
  incharge_name: string | null;
  sku_count: number;
  stock_value: number;
  open_po_count: number;
  scoped_user_count: number;
  in_use: boolean;
  reason: string | null;
}

export type GodownWithUsage = Godown & {
  skuCount: number;
  stockValue: number;
  /** The deactivation guard, resolved in the same round trip as the list. */
  inUse: boolean;
  usageReason?: string;
};

export async function listGodownsWithUsage(): Promise<GodownWithUsage[]> {
  // Two requests rather than one per row: the usage endpoint returns every
  // godown's aggregates in a single query, so a fifty-godown list is still
  // two round trips.
  const [rows, usage] = await Promise.all([
    httpGet<GodownOut[]>("/catalog/godowns", { limit: 500 }),
    httpGet<GodownUsageOut[]>("/company/godown-usage"),
  ]);
  const byGodown = new Map(usage.map((u) => [u.godown_id, u]));
  return rows.map((g) => {
    const u = byGodown.get(g.id);
    return {
      ...toGodown(g, u?.incharge_name ?? ""),
      skuCount: u?.sku_count ?? 0,
      stockValue: u?.stock_value ?? 0,
      // A godown missing from the usage response is treated as in use:
      // refusing a delete we cannot vouch for is the safe failure.
      inUse: u?.in_use ?? true,
      usageReason: u ? u.reason ?? undefined : "usage could not be checked",
    };
  });
}

export interface GodownInput {
  name: string;
  code: string;
  city: string;
  stateCode: string;
  address: string;
  gstin: string | null;
  inchargeUserId: Id | null;
  capacityValue?: number;
  capacityUomId?: Id | null;
  isDefault?: boolean;
}

export async function createGodown(input: GodownInput): Promise<Godown> {
  const errors: { field: string; message: string }[] = [];
  if (!input.name.trim()) errors.push({ field: "name", message: "Enter a godown name." });
  if (!input.stateCode) errors.push({ field: "stateCode", message: "Choose the state — it decides the tax treatment." });
  // The name/code clash checks that used to run against the mock `godowns`
  // table are dropped (same judgment call as catalog.api.ts's SKU check):
  // that table no longer reflects what actually exists once godowns are
  // real. The backend enforces uniqueness itself and returns a 422.
  if (errors.length) validationFailed(errors);

  const out = await httpPost<GodownOut>("/catalog/godowns", {
    name: input.name.trim(),
    code: input.code.trim() ? input.code.trim().toUpperCase() : undefined,
    city: input.city,
    state_code: input.stateCode,
    address: input.address,
    gstin: input.gstin,
    is_default: input.isDefault ?? false,
    is_active: true,
    incharge_user_id: input.inchargeUserId,
    capacity_value: input.capacityValue ?? null,
    capacity_uom_id: input.capacityValue ? input.capacityUomId ?? null : null,
  });
  return toGodown(out);
}

export async function updateGodown(godownId: Id, input: GodownInput): Promise<Godown> {
  const errors: { field: string; message: string }[] = [];
  if (!input.name.trim()) errors.push({ field: "name", message: "Enter a godown name." });
  if (errors.length) validationFailed(errors);
  // The name-clash check and the "an open PO still delivers here, so
  // changing the state would change its tax treatment" guard both used to
  // query mock tables (`godowns`, `purchaseOrders`) that no longer reflect
  // reality once godowns and purchase orders are real — dropped, same
  // reasoning as `createGodown` above. The backend is expected to enforce
  // equivalent rules itself and return a 422/409.

  const out = await httpPatch<GodownOut>(`/catalog/godowns/${godownId}`, {
    name: input.name.trim(),
    code: input.code.trim() ? input.code.trim().toUpperCase() : undefined,
    city: input.city,
    state_code: input.stateCode,
    address: input.address,
    gstin: input.gstin,
    is_default: input.isDefault ?? false,
    // Sent even when empty, so clearing the in-charge or capacity sticks.
    incharge_user_id: input.inchargeUserId,
    capacity_value: input.capacityValue ?? null,
    capacity_uom_id: input.capacityValue ? input.capacityUomId ?? null : null,
  });
  return toGodown(out);
}

/**
 * The deactivation guard.
 *
 * Every clause is real now: stock on hand, open purchase orders delivering
 * here, and users scoped to this godown. It used to read the mock tables,
 * which meant a godown holding real stock reported itself free to retire.
 */
export async function getGodownUsage(godownId: Id): Promise<{ inUse: boolean; reason?: string }> {
  const u = await httpGet<GodownUsageOut>(`/company/godown-usage/${godownId}`);
  return { inUse: u.in_use, reason: u.reason ?? undefined };
}

export async function deactivateGodown(godownId: Id): Promise<void> {
  const godown = await httpGet<GodownOut>(`/catalog/godowns/${godownId}`);
  const usage = await getGodownUsage(godownId); // stays mock — see above
  if (usage.inUse) reject(`${godown.name} cannot be removed — ${usage.reason}.`, "BR-MD-10");
  if (godown.is_default) reject("Set another godown as the default first.", "BR-MD-11");
  await httpDelete(`/catalog/godowns/${godownId}`);
}

/* -------------------------------------------------------------- Settings */

export async function getCompanySettings(): Promise<{ company: Company; settings: CompanySettings }> {
  const [profileOut, settingsOut] = await Promise.all([
    httpGet<CompanyProfileOut>("/company/profile"),
    httpGet<CompanySettingsOut>("/company/settings"),
  ]);
  return { company: toCompany(profileOut), settings: await toCompanySettings(settingsOut) };
}

export async function updateCompanySettings(patch: Partial<CompanySettings>): Promise<CompanySettings> {
  const errors: { field: string; message: string }[] = [];
  if (patch.grnExcessTolerancePct !== undefined && (patch.grnExcessTolerancePct < 0 || patch.grnExcessTolerancePct > 50)) {
    errors.push({ field: "grnExcessTolerancePct", message: "Tolerance must be between 0 and 50%." });
  }
  if (patch.variancePriceTolerancePct !== undefined && patch.variancePriceTolerancePct < 0) {
    errors.push({ field: "variancePriceTolerancePct", message: "Tolerance cannot be negative." });
  }
  if (patch.requirePoApprovalAbove != null && patch.requirePoApprovalAbove < 0) {
    errors.push({ field: "requirePoApprovalAbove", message: "Threshold cannot be negative." });
  }
  if ("aiNeverAutoApproveFinancials" in patch && patch.aiNeverAutoApproveFinancials !== true) {
    errors.push({
      field: "aiNeverAutoApproveFinancials",
      message: "Financial values always need a person's approval — this cannot be turned off.",
    });
  }
  if (errors.length) validationFailed(errors);

  // Only send keys actually present in `patch` (PATCH's exclude_unset
  // semantics, rule 6). `patch.numbering` has no backend field (document
  // sequences stay fully on mock) — silently dropped if present.
  const body: Record<string, unknown> = {};
  if (patch.currencyCode !== undefined) body.currency_code = patch.currencyCode;
  if (patch.defaultGstRate !== undefined) body.default_gst_rate = patch.defaultGstRate;
  if (patch.roundingMode !== undefined) body.rounding_mode = patch.roundingMode;
  if (patch.financialYearStartMonth !== undefined) body.financial_year_start_month = patch.financialYearStartMonth;
  if (patch.defaultGodownId !== undefined) body.default_godown_id = patch.defaultGodownId;
  if (patch.aiAutoProcess !== undefined) body.ai_auto_process = patch.aiAutoProcess;
  if (patch.aiReviewConfidenceThreshold !== undefined) body.ai_review_confidence_threshold = patch.aiReviewConfidenceThreshold;
  if (patch.aiSuggestWhileTyping !== undefined) body.ai_suggest_while_typing = patch.aiSuggestWhileTyping;
  if (patch.aiNeverAutoApproveFinancials !== undefined) body.ai_never_autoapprove_financials = patch.aiNeverAutoApproveFinancials;
  if (patch.lowStockThresholdMode !== undefined) body.low_stock_threshold_mode = patch.lowStockThresholdMode;
  if (patch.alertEmailCritical !== undefined) body.alert_email_critical = patch.alertEmailCritical;
  if (patch.alertDailyLowStockDigest !== undefined) body.alert_daily_low_stock_digest = patch.alertDailyLowStockDigest;
  if (patch.alertPoDelayNotify !== undefined) body.alert_po_delay_notify = patch.alertPoDelayNotify;
  if (patch.poDelayGraceDays !== undefined) body.po_delay_grace_days = patch.poDelayGraceDays;
  if (patch.allowGrnExcessReceipt !== undefined) body.allow_grn_excess_receipt = patch.allowGrnExcessReceipt;
  if (patch.grnExcessTolerancePct !== undefined) body.grn_excess_tolerance_pct = patch.grnExcessTolerancePct;
  if (patch.requirePoApprovalAbove !== undefined) body.require_po_approval_above = patch.requirePoApprovalAbove;
  if (patch.requireMakerChecker !== undefined) body.require_maker_checker = patch.requireMakerChecker;
  if (patch.allowNegativeStock !== undefined) body.allow_negative_stock = patch.allowNegativeStock;
  if (patch.inventoryLockedThrough !== undefined) body.inventory_locked_through = patch.inventoryLockedThrough;
  if (patch.variancePriceTolerancePct !== undefined) body.variance_price_tolerance_pct = patch.variancePriceTolerancePct;
  if (patch.varianceAmountTolerance !== undefined) body.variance_amount_tolerance = patch.varianceAmountTolerance;

  const out = await httpPatch<CompanySettingsOut>("/company/settings", body);
  return toCompanySettings(out);
}

export async function updateCompanyProfile(patch: Partial<Company>): Promise<Company> {
  const body: Record<string, unknown> = {};
  if (patch.name !== undefined) body.name = patch.name;
  if (patch.legalName !== undefined) body.legal_name = patch.legalName;
  if (patch.gstin !== undefined) body.gstin = patch.gstin;
  if (patch.pan !== undefined) body.pan = patch.pan;
  if (patch.stateCode !== undefined) body.state_code = patch.stateCode;
  if (patch.stateName !== undefined) body.state_name = patch.stateName;
  if (patch.city !== undefined) body.city = patch.city;
  if (patch.addressLine1 !== undefined) body.address_line1 = patch.addressLine1;
  if (patch.addressLine2 !== undefined) body.address_line2 = patch.addressLine2;
  if (patch.pincode !== undefined) body.pincode = patch.pincode;
  if (patch.email !== undefined) body.email = patch.email;
  if (patch.phone !== undefined) body.phone = patch.phone;
  // `plan`/`status`/`suspendedAt`/`suspendedReason`/`ownerEmail` have no
  // write path on this endpoint (plan/status are platform-managed, the rest
  // have no backend column) — dropped if present, known gap.

  const out = await httpPatch<CompanyProfileOut>("/company/profile", body);
  return toCompany(out);
}

/** `GET /company/document-sequences` — mirrors `DocumentSequenceOut`. */
interface DocumentSequenceOut {
  id: string;
  doc_type: string;
  financial_year: string;
  prefix: string;
  padding: number;
  next_number: number;
}

/**
 * The live numbering series.
 *
 * `nextNumber` is the allocator's own counter, not a setting — the Settings
 * screen used to render seeded mock values here, so someone reading "next
 * PO: 1" while the allocator sat at 108 had no way to tell.
 */
export async function listDocumentSequences(): Promise<DocumentSequence[]> {
  const rows = await httpGet<DocumentSequenceOut[]>("/company/document-sequences");
  return rows.map((s) => ({
    id: s.id,
    docType: s.doc_type as DocumentSequence["docType"],
    financialYear: s.financial_year,
    prefix: s.prefix,
    padding: s.padding,
    nextNumber: s.next_number,
  }));
}

/**
 * Close the inventory period. Nothing may be posted on or before the closing
 * date afterwards (BR-INV-08).
 */
export async function closeInventoryPeriod(throughDate: string): Promise<CompanySettings> {
  // The "already closed through a later date" pre-check used to run against
  // the mock settings row — dropped here; the backend enforces its own
  // ordering rule and returns a 422 on an invalid date, matching the shape
  // `validationFailed` throws.
  const out = await httpPatch<CompanySettingsOut>("/company/settings", { inventory_locked_through: throughDate });
  return toCompanySettings(out);
}

/* ------------------------------------------------------- Platform console */

/**
 * Every tenant on the installation, for a platform admin only.
 *
 * These all hit `/platform/*`, which runs on the BYPASSRLS session behind
 * `require_platform_admin` — a tenant Owner gets 403 on every one of them,
 * so nothing here is reachable from a normal session however the UI is
 * poked. Filtering and search happen on the server (the list can span every
 * company on the installation), so this module does not re-query in memory
 * the way the tenant-level lists do.
 */

/** `/platform/companies` — `platform/schemas.py::PlatformCompanyOut`. */
interface PlatformCompanyOut {
  id: string;
  name: string;
  legal_name: string | null;
  gstin: string | null;
  pan: string | null;
  state_code: string;
  state_name: string;
  city: string | null;
  email: string | null;
  phone: string | null;
  plan: Company["plan"];
  status: Company["status"];
  suspended_at: string | null;
  suspended_reason: string | null;
  onboarded_on: string;
  user_count: number;
  sku_count: number;
  owner_name: string;
  owner_email: string;
}

export interface CompanyListRow extends Company {
  userCount: number;
  skuCount: number;
  ownerName: string;
}

function toCompanyRow(o: PlatformCompanyOut): CompanyListRow {
  return {
    id: o.id,
    name: o.name,
    legalName: o.legal_name ?? undefined,
    gstin: o.gstin,
    pan: o.pan,
    stateCode: o.state_code,
    stateName: o.state_name,
    city: o.city ?? "",
    addressLine1: "",
    email: o.email ?? undefined,
    phone: o.phone ?? undefined,
    plan: o.plan,
    status: o.status,
    suspendedAt: o.suspended_at,
    suspendedReason: o.suspended_reason,
    onboardedOn: o.onboarded_on,
    // Falls back to the pending Owner invitation server-side, so a company
    // onboarded a minute ago still shows who it belongs to.
    ownerEmail: o.owner_email,
    userCount: o.user_count,
    skuCount: o.sku_count,
    ownerName: o.owner_name,
  };
}

export interface PlatformKpis {
  companies: number;
  activeCompanies: number;
  suspendedCompanies: number;
  users: number;
  activeUsers30d: number;
}

export async function getPlatformKpis(): Promise<PlatformKpis> {
  const o = await httpGet<{
    companies: number;
    active_companies: number;
    suspended_companies: number;
    users: number;
    active_users_30d: number;
  }>("/platform/kpis");
  return {
    companies: o.companies,
    activeCompanies: o.active_companies,
    suspendedCompanies: o.suspended_companies,
    users: o.users,
    activeUsers30d: o.active_users_30d,
  };
}

export async function listCompanies(params: ListParams = {}): Promise<ListResponse<CompanyListRow>> {
  const filters = (params.filters ?? {}) as Record<string, string | undefined>;
  const rows = (
    await httpGet<PlatformCompanyOut[]>("/platform/companies", {
      limit: params.limit ?? 200,
      q: params.q?.trim() || undefined,
      status: filters.status || undefined,
      plan: filters.plan || undefined,
    })
  ).map(toCompanyRow);
  // The server has already searched and filtered — facets would need a
  // second cross-tenant aggregate, and the toolbar's options are fixed
  // vocabularies (plan, status) rather than whatever happens to be present.
  return { items: rows, total: rows.length, nextCursor: null };
}

export async function getCompany(companyId: Id): Promise<CompanyListRow> {
  return toCompanyRow(await httpGet<PlatformCompanyOut>(`/platform/companies/${companyId}`));
}

export interface OnboardCompanyInput {
  name: string;
  legalName?: string;
  gstin?: string;
  stateCode: string;
  stateName: string;
  city?: string;
  email?: string;
  phone?: string;
  plan: Company["plan"];
  ownerEmail: string;
  ownerFullName: string;
}

export interface OnboardedCompany {
  company: CompanyListRow;
  ownerEmail: string;
  /** Development only — elsewhere the emailed link is the only copy. */
  invitationToken?: string;
  /**
   * BR-AUTH-13: the owner email already had a login, so the new company was
   * linked to it (they switch into it from the header) instead of an
   * invitation being sent.
   */
  ownerLinked: boolean;
}

/**
 * Stands up a tenant and *invites* its first Owner.
 *
 * There is deliberately no password field: the Owner sets their own from
 * the invitation link, so the person who pressed this button never knows it.
 */
export async function onboardCompany(input: OnboardCompanyInput): Promise<OnboardedCompany> {
  const errors: { field: string; message: string }[] = [];
  if (input.name.trim().length < 2) errors.push({ field: "name", message: "Enter the company's name." });
  if (!/^\d{2}$/.test(input.stateCode.trim())) {
    errors.push({ field: "stateCode", message: "Choose the company's state." });
  }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(input.ownerEmail.trim())) {
    errors.push({ field: "ownerEmail", message: "That doesn't look like an email address." });
  }
  if (input.ownerFullName.trim().length < 2) {
    errors.push({ field: "ownerFullName", message: "Enter the owner's name." });
  }
  if (input.gstin?.trim() && input.gstin.trim().length !== 15) {
    errors.push({ field: "gstin", message: "A GSTIN is 15 characters." });
  }
  if (errors.length) validationFailed(errors);

  const out = await httpPost<{
    company: PlatformCompanyOut;
    owner_email: string;
    invitation_token: string | null;
    owner_linked: boolean;
  }>("/platform/companies", {
    name: input.name.trim(),
    legal_name: input.legalName?.trim() || null,
    gstin: input.gstin?.trim().toUpperCase() || null,
    state_code: input.stateCode.trim(),
    state_name: input.stateName.trim(),
    city: input.city?.trim() || null,
    email: input.email?.trim() || null,
    phone: input.phone?.trim() || null,
    plan: input.plan,
    owner_email: input.ownerEmail.trim(),
    owner_full_name: input.ownerFullName.trim(),
  });
  return {
    company: toCompanyRow(out.company),
    ownerEmail: out.owner_email,
    invitationToken: out.invitation_token ?? undefined,
    ownerLinked: !!out.owner_linked,
  };
}

/* ------------------------------------------ Linked owners (BR-AUTH-13) */

/** Someone whose login lives in another company but who can switch into
 * this one. The company's own users come from `listPlatformUsers`. */
export interface CompanyMember {
  userId: Id;
  companyId: Id;
  email: string;
  fullName: string;
  homeCompanyId: Id | null;
  homeCompanyName: string;
  roleCode: string;
  roleName: string;
  status: string;
  addedAt: string;
  lastLoginAt: string | null;
}

interface PlatformMemberOut {
  user_id: string;
  company_id: string;
  email: string;
  full_name: string;
  home_company_id: string | null;
  home_company_name: string;
  role_code: string;
  role_name: string;
  status: string;
  added_at: string;
  last_login_at: string | null;
}

function toMember(m: PlatformMemberOut): CompanyMember {
  return {
    userId: m.user_id,
    companyId: m.company_id,
    email: m.email,
    fullName: m.full_name,
    homeCompanyId: m.home_company_id,
    homeCompanyName: m.home_company_name,
    roleCode: m.role_code,
    roleName: m.role_name,
    status: m.status,
    addedAt: m.added_at,
    lastLoginAt: m.last_login_at,
  };
}

export async function listCompanyMembers(companyId: Id): Promise<CompanyMember[]> {
  const rows = await httpGet<PlatformMemberOut[]>(`/platform/companies/${companyId}/members`);
  return rows.map(toMember);
}

/** Give an existing login Owner access to this company. */
export async function addCompanyMember(companyId: Id, email: string): Promise<CompanyMember> {
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
    validationFailed([{ field: "email", message: "That doesn't look like an email address." }]);
  }
  return toMember(
    await httpPost<PlatformMemberOut>(`/platform/companies/${companyId}/members`, { email: email.trim() }),
  );
}

export async function removeCompanyMember(companyId: Id, userId: Id): Promise<void> {
  await httpDelete(`/platform/companies/${companyId}/members/${userId}`);
}

export async function updateCompany(
  companyId: Id,
  patch: Partial<Pick<OnboardCompanyInput, "name" | "legalName" | "gstin" | "city" | "email" | "phone" | "plan">>,
): Promise<CompanyListRow> {
  const body: Record<string, unknown> = {};
  if (patch.name !== undefined) body.name = patch.name.trim();
  if (patch.legalName !== undefined) body.legal_name = patch.legalName.trim() || null;
  if (patch.gstin !== undefined) body.gstin = patch.gstin.trim().toUpperCase() || null;
  if (patch.city !== undefined) body.city = patch.city.trim() || null;
  if (patch.email !== undefined) body.email = patch.email.trim() || null;
  if (patch.phone !== undefined) body.phone = patch.phone.trim() || null;
  if (patch.plan !== undefined) body.plan = patch.plan;
  return toCompanyRow(await httpPatch<PlatformCompanyOut>(`/platform/companies/${companyId}`, body));
}

/**
 * Suspending takes effect on the tenant's very next request (BR-AUTH-04) —
 * `assert_session_live` re-reads the company row, so live tokens stop
 * working without anything here enumerating sessions.
 */
export async function setCompanyStatus(
  companyId: Id,
  status: Company["status"],
  reason?: string,
): Promise<CompanyListRow> {
  if (status === "suspended") {
    if ((reason ?? "").trim().length < 3) {
      validationFailed([{ field: "reason", message: "Say why — the company's users will see this." }]);
    }
    return toCompanyRow(
      await httpPost<PlatformCompanyOut>(`/platform/companies/${companyId}/suspend`, { reason: reason!.trim() }),
    );
  }
  return toCompanyRow(await httpPost<PlatformCompanyOut>(`/platform/companies/${companyId}/reactivate`, {}));
}

/** `/platform/users` — platform admins are excluded server-side. */
interface PlatformUserOut {
  id: string;
  company_id: string | null;
  company_name: string;
  email: string;
  full_name: string;
  role_code: string;
  role_name: string;
  status: string;
  last_login_at: string | null;
}

export interface PlatformUserRow {
  id: Id;
  companyId: Id | null;
  companyName: string;
  email: string;
  fullName: string;
  roleCode: string;
  roleName: string;
  status: string;
  lastLoginAt: string | null;
}

export async function listPlatformUsers(companyId?: Id, q?: string): Promise<PlatformUserRow[]> {
  const rows = await httpGet<PlatformUserOut[]>("/platform/users", {
    limit: 300,
    company_id: companyId || undefined,
    q: q?.trim() || undefined,
  });
  return rows.map((u) => ({
    id: u.id,
    companyId: u.company_id,
    companyName: u.company_name,
    email: u.email,
    fullName: u.full_name,
    roleCode: u.role_code,
    roleName: u.role_name,
    status: u.status,
    lastLoginAt: u.last_login_at,
  }));
}

/**
 * Activate/deactivate one of a tenant's users from the console.
 *
 * Deliberately narrower than `updateUserAccess` (no role or godown-scope
 * editing) — see `console_service.update_user_status` on the backend for
 * why. The server still refuses to deactivate a tenant's last active Owner
 * (BR-AUTH-10) and ends the user's live sessions on deactivation.
 */
export async function setTenantUserStatus(userId: Id, status: "active" | "inactive"): Promise<PlatformUserRow> {
  const u = await httpPatch<PlatformUserOut>(`/platform/users/${userId}`, { status });
  return {
    id: u.id,
    companyId: u.company_id,
    companyName: u.company_name,
    email: u.email,
    fullName: u.full_name,
    roleCode: u.role_code,
    roleName: u.role_name,
    status: u.status,
    lastLoginAt: u.last_login_at,
  };
}

/* ----------------------------- Pending invitations (platform console) */

/** `GET /platform/companies/{id}/invitations`. */
interface PlatformInvitationOut {
  id: string;
  email: string;
  full_name: string;
  role_code: string;
  role_name: string;
  status: string;
  invited_at: string;
  expires_at: string;
  last_sent_at: string | null;
  resend_count: number;
  is_expired: boolean;
}

export interface CompanyInvitationRow {
  id: Id;
  email: string;
  fullName: string;
  roleName: string;
  invitedAt: string;
  expiresAt: string;
  lastSentAt: string | null;
  resendCount: number;
  isExpired: boolean;
}

/** Invitations at one company that nobody has accepted yet. */
export async function listCompanyInvitations(companyId: Id): Promise<CompanyInvitationRow[]> {
  const rows = await httpGet<PlatformInvitationOut[]>(`/platform/companies/${companyId}/invitations`);
  return rows.map((i) => ({
    id: i.id,
    email: i.email,
    fullName: i.full_name,
    roleName: i.role_name || i.role_code,
    invitedAt: i.invited_at,
    expiresAt: i.expires_at,
    lastSentAt: i.last_sent_at,
    resendCount: i.resend_count,
    isExpired: i.is_expired,
  }));
}

export interface ResentInvitation {
  email: string;
  expiresAt: string;
  /** Development only — the backend returns the raw token nowhere else. */
  inviteLink?: string;
}

/** Issues a new link (the old one stops working) and emails it again. */
export async function resendCompanyInvitation(companyId: Id, invitationId: Id): Promise<ResentInvitation> {
  const out = await httpPost<{ email: string; expires_at: string; invitation_token: string | null }>(
    `/platform/companies/${companyId}/invitations/${invitationId}/resend`,
  );
  return { email: out.email, expiresAt: out.expires_at, inviteLink: inviteLinkFor(out.invitation_token) };
}

/** Invites another Owner to an existing company (e.g. to replace the
 * current one — BR-AUTH-10 needs the new Owner in place first). */
export async function inviteCompanyOwner(
  companyId: Id,
  input: { email: string; fullName: string },
): Promise<ResentInvitation> {
  const out = await httpPost<{ email: string; expires_at: string; invitation_token: string | null }>(
    `/platform/companies/${companyId}/invitations`,
    { email: input.email.trim(), full_name: input.fullName.trim() },
  );
  return { email: out.email, expiresAt: out.expires_at, inviteLink: inviteLinkFor(out.invitation_token) };
}

/**
 * Active Owners of a company: its own Owner users plus linked Owners. Same
 * rule the server applies for BR-AUTH-10 — used only to disable buttons
 * the server would refuse anyway.
 */
export function countActiveOwners(users: PlatformUserRow[], members: CompanyMember[]): number {
  const ids = new Set<string>();
  users.filter((u) => u.roleCode === "owner" && u.status === "active").forEach((u) => ids.add(u.id));
  members.filter((m) => m.roleCode === "owner" && m.status === "active").forEach((m) => ids.add(m.userId));
  return ids.size;
}

/* ------------------------------------ All-users directory (console) */

interface PlatformDirectoryUserOut {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  status: string;
  last_login_at: string | null;
  created_at: string | null;
  companies: {
    company_id: string;
    company_name: string;
    role_code: string;
    role_name: string;
    status: string;
    is_home: boolean;
  }[];
}

export interface DirectoryUserCompany {
  companyId: Id;
  companyName: string;
  roleCode: string;
  roleName: string;
  status: string;
  isHome: boolean;
}

export interface DirectoryUserRow {
  id: Id;
  email: string;
  fullName: string;
  phone: string | null;
  status: string;
  lastLoginAt: string | null;
  /** Home company first, then every linked company. */
  companies: DirectoryUserCompany[];
}

function toDirectoryUser(u: PlatformDirectoryUserOut): DirectoryUserRow {
  return {
    id: u.id,
    email: u.email,
    fullName: u.full_name,
    phone: u.phone,
    status: u.status,
    lastLoginAt: u.last_login_at,
    companies: u.companies.map((c) => ({
      companyId: c.company_id,
      companyName: c.company_name,
      roleCode: c.role_code,
      roleName: c.role_name || c.role_code,
      status: c.status,
      isHome: c.is_home,
    })),
  };
}

export interface DirectoryFilters {
  q?: string;
  companyId?: Id;
  status?: string;
}

/** Every tenant user on the platform; the company filter matches home or
 * linked companies. */
export async function listUserDirectory(filters: DirectoryFilters = {}): Promise<DirectoryUserRow[]> {
  const rows = await httpGet<PlatformDirectoryUserOut[]>("/platform/user-directory", {
    limit: 1000,
    q: filters.q?.trim() || undefined,
    company_id: filters.companyId || undefined,
    status: filters.status || undefined,
  });
  return rows.map(toDirectoryUser);
}

/** Name and phone only — email is the login and role stays tenant-side. */
export async function updatePlatformUserProfile(
  userId: Id,
  patch: { fullName: string; phone: string },
): Promise<DirectoryUserRow> {
  const out = await httpPatch<PlatformDirectoryUserOut>(`/platform/users/${userId}/profile`, {
    full_name: patch.fullName.trim(),
    phone: patch.phone.trim(),
  });
  return toDirectoryUser(out);
}

/** `/platform/activity` — the cross-tenant audit feed. */
interface PlatformActivityOut {
  id: string;
  created_at: string;
  company_id: string | null;
  company_name: string;
  entity_type: string;
  entity_id: string | null;
  entity_label: string;
  action: string;
  description: string | null;
  actor_user_id: string | null;
  actor_name: string;
  actor_role: string;
  impersonated_by: string | null;
}

export interface PlatformActivityRow {
  id: Id;
  createdAt: string;
  companyId: Id | null;
  companyName: string;
  entityType: string;
  entityId: Id;
  entityLabel: string;
  action: string;
  description?: string;
  actorUserId: Id | null;
  actorName: string;
  actorRole?: string;
  impersonatedBy?: Id | null;
  impersonated: boolean;
}

export async function listPlatformActivity(limit = 100, companyId?: Id): Promise<PlatformActivityRow[]> {
  const rows = await httpGet<PlatformActivityOut[]>("/platform/activity", {
    limit,
    company_id: companyId || undefined,
  });
  return rows.map((a) => ({
    id: a.id,
    createdAt: a.created_at,
    companyId: a.company_id,
    companyName: a.company_name,
    entityType: a.entity_type,
    entityId: a.entity_id ?? "",
    entityLabel: a.entity_label,
    action: a.action,
    description: a.description ?? undefined,
    actorUserId: a.actor_user_id,
    actorName: a.actor_name,
    actorRole: a.actor_role || undefined,
    impersonatedBy: a.impersonated_by,
    impersonated: !!a.impersonated_by,
  }));
}

/* ------------------------------------------------- Outgoing email / SMTP */

/** `/company/email-settings` — `platform/schemas.py::EmailSettingsOut`. */
interface EmailSettingsOut {
  company_id: string;
  provider: "console" | "smtp";
  from_address: string | null;
  from_name: string | null;
  smtp_host: string | null;
  smtp_port: number;
  smtp_username: string | null;
  smtp_use_tls: boolean;
  has_password: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_error: string | null;
}

export interface EmailSettings {
  provider: "console" | "smtp";
  fromAddress: string;
  fromName: string;
  smtpHost: string;
  smtpPort: number;
  smtpUsername: string;
  smtpUseTls: boolean;
  /** The password itself is write-only — this is all the API will say. */
  hasPassword: boolean;
  lastTestAt: string | null;
  lastTestOk: boolean | null;
  lastTestError: string | null;
}

function toEmailSettings(o: EmailSettingsOut): EmailSettings {
  return {
    provider: o.provider,
    fromAddress: o.from_address ?? "",
    fromName: o.from_name ?? "",
    smtpHost: o.smtp_host ?? "",
    smtpPort: o.smtp_port,
    smtpUsername: o.smtp_username ?? "",
    smtpUseTls: o.smtp_use_tls,
    hasPassword: o.has_password,
    lastTestAt: o.last_test_at,
    lastTestOk: o.last_test_ok,
    lastTestError: o.last_test_error,
  };
}

export async function getEmailSettings(): Promise<EmailSettings> {
  return toEmailSettings(await httpGet<EmailSettingsOut>("/company/email-settings"));
}

export interface EmailSettingsInput extends Omit<EmailSettings, "hasPassword" | "lastTestAt" | "lastTestOk" | "lastTestError"> {
  /** Omit to keep the stored password, "" to clear it. */
  smtpPassword?: string;
}

export async function saveEmailSettings(input: EmailSettingsInput): Promise<EmailSettings> {
  const errors: { field: string; message: string }[] = [];
  if (input.provider === "smtp") {
    if (!input.smtpHost.trim()) errors.push({ field: "smtpHost", message: "Enter your mail server's host name." });
    if (!input.fromAddress.trim()) errors.push({ field: "fromAddress", message: "Enter the address mail is sent from." });
  }
  if (input.fromAddress && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(input.fromAddress.trim())) {
    errors.push({ field: "fromAddress", message: "That doesn't look like an email address." });
  }
  if (input.smtpPort < 1 || input.smtpPort > 65535) {
    errors.push({ field: "smtpPort", message: "Port must be between 1 and 65535." });
  }
  if (errors.length) validationFailed(errors);

  const body: Record<string, unknown> = {
    provider: input.provider,
    from_address: input.fromAddress.trim() || null,
    from_name: input.fromName.trim() || null,
    smtp_host: input.smtpHost.trim() || null,
    smtp_port: input.smtpPort,
    smtp_username: input.smtpUsername.trim() || null,
    smtp_use_tls: input.smtpUseTls,
  };
  if (input.smtpPassword !== undefined) body.smtp_password = input.smtpPassword;
  return toEmailSettings(await httpPut<EmailSettingsOut>("/company/email-settings", body));
}

/** Sends one message with the *saved* settings, and records the outcome. */
export async function sendTestEmail(toAddress?: string): Promise<{ sent: boolean; toAddress: string; error?: string }> {
  const out = await httpPost<{ sent: boolean; provider: string; to_address: string; error: string | null }>(
    "/company/email-settings/test",
    { to_address: toAddress?.trim() || null },
  );
  return { sent: out.sent, toAddress: out.to_address, error: out.error ?? undefined };
}


/* ------------------------------------------------------- Custom roles */

export interface RoleInput {
  name: string;
  description?: string;
  permissions: PermissionCode[];
  /** Start from another role's permission set. */
  cloneFromRoleId?: Id;
}

function validateRole(input: RoleInput, { requirePermissions = true } = {}): void {
  const errors: { field: string; message: string }[] = [];
  if (input.name.trim().length < 2) errors.push({ field: "name", message: "Give the role a name." });
  if (requirePermissions && input.permissions.length === 0 && !input.cloneFromRoleId) {
    errors.push({ field: "permissions", message: "Choose at least one thing this role may do." });
  }
  if (errors.length) validationFailed(errors);
}

export async function createRole(input: RoleInput): Promise<RoleWithUsage> {
  validateRole(input);
  const created = await httpPost<RoleOut>("/roles", {
    name: input.name.trim(),
    description: input.description?.trim() || null,
    permissions: input.permissions,
    clone_from_role_id: input.cloneFromRoleId ?? null,
  });
  roleCache = null;
  return toRole(created);
}

export async function updateRole(
  roleId: Id,
  patch: { name?: string; description?: string; permissions?: PermissionCode[] },
): Promise<RoleWithUsage> {
  if (patch.name !== undefined || patch.permissions !== undefined) {
    validateRole(
      { name: patch.name ?? "ok", permissions: patch.permissions ?? [] },
      { requirePermissions: patch.permissions !== undefined },
    );
  }
  const body: Record<string, unknown> = {};
  if (patch.name !== undefined) body.name = patch.name.trim();
  if (patch.description !== undefined) body.description = patch.description.trim() || null;
  if (patch.permissions !== undefined) body.permissions = patch.permissions;
  const updated = await httpPatch<RoleOut>(`/roles/${roleId}`, body);
  roleCache = null;
  return toRole(updated);
}

/** Whether a role can be deleted, and what is holding it if not. */
export async function getRoleUsage(roleId: Id): Promise<{ inUse: boolean; reason?: string }> {
  const out = await httpGet<{ in_use: boolean; reason: string | null }>(`/roles/${roleId}/usage`);
  return { inUse: out.in_use, reason: out.reason ?? undefined };
}

export async function deleteRole(roleId: Id): Promise<void> {
  await httpDelete(`/roles/${roleId}`);
  roleCache = null;
}
