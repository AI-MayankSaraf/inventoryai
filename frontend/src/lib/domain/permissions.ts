/**
 * Permission evaluation for the UI.
 *
 * ⚠️ This is presentation logic, not security. It decides what a user is
 * *offered* — which nav items render, which buttons are enabled, which
 * godowns appear in a picker. It cannot protect anything: the data is in the
 * browser and any check here can be bypassed with devtools.
 *
 * The real enforcement is a server-side dependency on every endpoint
 * (`07_RBAC_MATRIX.md`). Every guard in this file is mirrored there, and the
 * matrix is the contract: if a check exists here, the same check must exist on
 * the endpoint. Nothing in the app may claim these checks are security (C4).
 */

import type { GodownScope, Id, PermissionCode, SessionUser } from "@/types";

export const PERMISSION_ENFORCEMENT_NOTE =
  "Shown according to your role. Server-side checks are the actual enforcement.";

export function hasPermission(
  user: Pick<SessionUser, "permissions"> | null | undefined,
  permission: PermissionCode,
): boolean {
  if (!user) return false;
  return user.permissions.includes(permission);
}

/**
 * A handful of actions (e.g. editing a product's catalog record) are
 * restricted to the Owner role specifically, rather than to whoever holds a
 * given permission — several roles can legitimately hold `product.update`,
 * but the business wants only the Owner offered the button. Role, not
 * permission, on purpose (C5 still applies: this is presentation only).
 */
export function isOwner(user: Pick<SessionUser, "roleCode"> | null | undefined): boolean {
  return user?.roleCode === "owner";
}

export function hasAny(
  user: Pick<SessionUser, "permissions"> | null | undefined,
  permissions: PermissionCode[],
): boolean {
  if (!user || permissions.length === 0) return false;
  return permissions.some((p) => user.permissions.includes(p));
}

export function hasAll(
  user: Pick<SessionUser, "permissions"> | null | undefined,
  permissions: PermissionCode[],
): boolean {
  if (!user) return false;
  return permissions.every((p) => user.permissions.includes(p));
}

/* ------------------------------------------------------- Godown scoping */

/** Can this user see data for a godown at all (BR-AUTH-12)? */
export function canSeeGodown(
  user: Pick<SessionUser, "permissions" | "godownScope"> | null | undefined,
  godownId: Id | null | undefined,
): boolean {
  if (!user) return false;
  if (!godownId) return true;
  if (user.permissions.includes("inventory.view_all")) return true;
  return scopeAllows(user.godownScope, godownId);
}

/** Can this user *act* (receive, adjust, transfer) in a godown? */
export function canActInGodown(
  user: Pick<SessionUser, "permissions" | "godownScope"> | null | undefined,
  godownId: Id | null | undefined,
): boolean {
  if (!user || !godownId) return false;
  if (user.permissions.includes("inventory.transfer_any")) return true;
  return scopeAllows(user.godownScope, godownId);
}

export function scopeAllows(scope: GodownScope | undefined, godownId: Id): boolean {
  if (!scope) return false;
  return scope.all || scope.godownIds.includes(godownId);
}

/** The godown ids a picker should offer this user. */
export function visibleGodownIds(
  user: Pick<SessionUser, "permissions" | "godownScope"> | null | undefined,
  allGodownIds: Id[],
): Id[] {
  if (!user) return [];
  if (user.permissions.includes("inventory.view_all") || user.godownScope.all) return allGodownIds;
  return allGodownIds.filter((id) => user.godownScope.godownIds.includes(id));
}

/* --------------------------------------------------- Value-based limits */

/**
 * Approval above a configured value needs the elevated permission
 * (BR-PO-03). The threshold lives in company settings, not in a component.
 */
export function canApprovePoValue(
  user: Pick<SessionUser, "permissions"> | null | undefined,
  totalAmount: number,
  approvalThreshold: number,
): boolean {
  if (!hasPermission(user, "po.approve")) return false;
  if (totalAmount <= approvalThreshold) return true;
  return hasPermission(user, "po.approve_high_value");
}

/* --------------------------------------------------- Route-level guards */

/** Which permission a top-level route requires, used by the sidebar and guards. */
export const ROUTE_PERMISSIONS: { prefix: string; permission: PermissionCode }[] = [
  { prefix: "/dashboard", permission: "dashboard.view" },
  { prefix: "/products", permission: "product.view" },
  { prefix: "/inventory", permission: "inventory.view" },
  { prefix: "/godowns", permission: "godown.view" },
  { prefix: "/suppliers", permission: "supplier.view" },
  { prefix: "/rfq", permission: "rfq.view" },
  { prefix: "/quotations", permission: "quotation.view" },
  { prefix: "/comparison", permission: "comparison.view" },
  { prefix: "/purchase-orders", permission: "po.view" },
  { prefix: "/proforma", permission: "proforma.view" },
  { prefix: "/goods-receipt", permission: "grn.view" },
  { prefix: "/supplier-invoices", permission: "invoice.view" },
  { prefix: "/purchase-returns", permission: "return.view" },
  { prefix: "/ai-documents", permission: "ai.view" },
  { prefix: "/schema-mappings", permission: "ai.manage_mappings" },
  { prefix: "/assistant", permission: "ai.assistant" },
  { prefix: "/alerts", permission: "alert.view" },
  { prefix: "/reports", permission: "report.view" },
  { prefix: "/users", permission: "user.view" },
  { prefix: "/roles", permission: "user.manage" },
  { prefix: "/settings", permission: "company.view" },
  { prefix: "/audit", permission: "audit.view" },
  { prefix: "/system-admin", permission: "platform.companies.view" },
];

export function permissionForRoute(pathname: string): PermissionCode | null {
  const match = ROUTE_PERMISSIONS.filter((r) => pathname.startsWith(r.prefix)).sort(
    (a, b) => b.prefix.length - a.prefix.length,
  )[0];
  return match?.permission ?? null;
}

export function canAccessRoute(
  user: Pick<SessionUser, "permissions"> | null | undefined,
  pathname: string,
): boolean {
  const permission = permissionForRoute(pathname);
  if (!permission) return true;
  return hasPermission(user, permission);
}

/* --------------------------------------------------------- Presentation */

export const PERMISSION_GROUPS: { label: string; permissions: PermissionCode[] }[] = [
  { label: "Dashboard", permissions: ["dashboard.view"] },
  {
    label: "Products & Master Data",
    permissions: [
      "product.view", "product.create", "product.update", "product.delete",
      "product.import", "product.export", "master.view", "master.manage",
    ],
  },
  {
    label: "Suppliers",
    permissions: ["supplier.view", "supplier.create", "supplier.update", "supplier.delete", "supplier.export"],
  },
  { label: "Godowns", permissions: ["godown.view", "godown.manage"] },
  {
    label: "Inventory",
    permissions: [
      "inventory.view", "inventory.view_all", "inventory.adjust", "inventory.transfer",
      "inventory.transfer_any", "inventory.override_expiry", "inventory.close_period", "inventory.export",
    ],
  },
  {
    label: "RFQ & Quotations",
    permissions: [
      "rfq.view", "rfq.create", "rfq.update", "rfq.delete", "rfq.send", "rfq.cancel", "rfq.import",
      "quotation.view", "quotation.create", "quotation.update", "quotation.delete",
      "quotation.approve", "quotation.reject",
      "comparison.view", "comparison.create", "comparison.decide", "comparison.convert",
    ],
  },
  {
    label: "Purchase Orders",
    permissions: [
      "po.view", "po.create", "po.update", "po.delete_draft", "po.submit",
      "po.approve", "po.approve_high_value", "po.send", "po.cancel", "po.close",
    ],
  },
  {
    label: "Proforma & Receiving",
    permissions: [
      "proforma.view", "proforma.create", "proforma.update", "proforma.approve",
      "proforma.approve_variance", "proforma.raise_query",
      "grn.view", "grn.create", "grn.update", "grn.confirm", "grn.reverse",
      "grn.receive_other_godown", "grn.allow_excess",
    ],
  },
  {
    label: "Invoices & Returns",
    permissions: [
      "invoice.view", "invoice.create", "invoice.update", "invoice.match",
      "invoice.approve", "invoice.dispute",
      "return.view", "return.create", "return.confirm",
    ],
  },
  {
    label: "Documents & AI",
    permissions: [
      "document.view", "document.upload", "document.delete", "document.download",
      "ai.view", "ai.review", "ai.approve_extraction", "ai.manage_mappings", "ai.assistant",
    ],
  },
  { label: "Alerts & Reports", permissions: ["alert.view", "alert.manage", "report.view", "report.export"] },
  {
    label: "Administration",
    permissions: ["user.view", "user.manage", "user.manage_owners", "company.view", "company.manage", "audit.view"],
  },
  {
    label: "Platform",
    permissions: [
      "platform.companies.view", "platform.companies.manage", "platform.users.view",
      "platform.impersonate", "platform.activity.view",
    ],
  },
];

const ACTION_LABELS: Record<string, string> = {
  view: "View", view_all: "View all godowns", create: "Create", update: "Edit",
  delete: "Delete", delete_draft: "Delete drafts", import: "Import", export: "Export",
  manage: "Manage", adjust: "Adjust stock", transfer: "Transfer stock",
  transfer_any: "Transfer between any godowns", override_expiry: "Override expiry block",
  close_period: "Close inventory period", send: "Send", cancel: "Cancel", close: "Close",
  submit: "Submit for approval", approve: "Approve", approve_high_value: "Approve high value",
  approve_variance: "Approve variance", reject: "Reject", decide: "Decide", convert: "Convert to PO",
  confirm: "Confirm", reverse: "Reverse", receive_other_godown: "Receive into any godown",
  allow_excess: "Allow excess receipt", match: "Run three-way match", dispute: "Raise dispute",
  raise_query: "Raise query", upload: "Upload", download: "Download", review: "Review",
  approve_extraction: "Approve extraction", manage_mappings: "Manage schema mappings",
  assistant: "Use the assistant", manage_owners: "Manage owners", impersonate: "Impersonate",
};

export function permissionLabel(code: PermissionCode): string {
  const [resource, action = ""] = code.split(".").slice(-2);
  const readable = ACTION_LABELS[action] ?? action.replace(/_/g, " ");
  const subject = resource.replace(/_/g, " ");
  return `${readable} ${subject}`.replace(/\s+/g, " ").trim();
}
