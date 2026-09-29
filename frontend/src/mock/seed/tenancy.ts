import type {
  Company,
  CompanySettings,
  DocumentSequence,
  Invitation,
  PermissionCode,
  Role,
  User,
} from "@/types";
import { COMPANY_ID, GODOWN, ROLE, USER } from "../ids";

const NOW = "2026-09-14T09:00:00+05:30";

export const companies: Company[] = [
  {
    id: COMPANY_ID,
    name: "Acme Traders",
    legalName: "Acme Traders Pvt Ltd",
    gstin: "23AACCA1234F1Z5",
    pan: "AACCA1234F",
    stateCode: "23",
    stateName: "Madhya Pradesh",
    city: "Indore",
    addressLine1: "Plot 14, Scheme 78",
    addressLine2: "Vijay Nagar",
    pincode: "452010",
    email: "orders@acmetraders.in",
    phone: "+91 731 456 7890",
    plan: "Growth",
    status: "active",
    onboardedOn: "2025-01-14",
    ownerEmail: "useradmin@acmetraders.in",
  },
  {
    id: "co_shree_ganesh",
    name: "Shree Ganesh Hardware",
    gstin: "27AABCS9012K1Z3",
    pan: "AABCS9012K",
    stateCode: "27",
    stateName: "Maharashtra",
    city: "Pune",
    addressLine1: "Shop 4, Laxmi Road",
    plan: "Starter",
    status: "active",
    onboardedOn: "2025-06-02",
    ownerEmail: "owner@shreeganesh.in",
  },
  {
    id: "co_konkan",
    name: "Konkan FoodMart Distributors",
    gstin: "27AADCK3456L1ZQ",
    pan: "AADCK3456L",
    stateCode: "27",
    stateName: "Maharashtra",
    city: "Ratnagiri",
    addressLine1: "Plot 8, MIDC",
    plan: "Growth",
    status: "active",
    onboardedOn: "2025-03-21",
    ownerEmail: "admin@konkanfoodmart.in",
  },
  {
    id: "co_bharat",
    name: "Bharat Electricals Co.",
    gstin: "24AACCB7788M1Z9",
    pan: "AACCB7788M",
    stateCode: "24",
    stateName: "Gujarat",
    city: "Ahmedabad",
    addressLine1: "Nr. Kalupur Gate",
    plan: "Trial",
    status: "active",
    onboardedOn: "2026-08-30",
    ownerEmail: "sales@bharatelectricals.in",
  },
  {
    id: "co_deccan",
    name: "Deccan Auto Spares",
    gstin: "29AAECD4455N1ZD",
    pan: "AAECD4455N",
    stateCode: "29",
    stateName: "Karnataka",
    city: "Hubli",
    addressLine1: "Gokul Road",
    plan: "Starter",
    status: "suspended",
    suspendedAt: "2026-08-11T10:00:00+05:30",
    suspendedReason: "Non-payment",
    onboardedOn: "2025-11-05",
    ownerEmail: "accounts@deccanauto.in",
  },
];

export const companySettings: CompanySettings[] = [
  {
    id: "cst_acme",
    companyId: COMPANY_ID,
    currencyCode: "INR",
    defaultGstRate: 18,
    roundingMode: "nearest",
    financialYearStartMonth: 4,
    defaultGodownId: GODOWN.main,

    aiAutoProcess: true,
    aiReviewConfidenceThreshold: 90,
    aiSuggestWhileTyping: true,
    aiNeverAutoApproveFinancials: true,

    lowStockThresholdMode: "reorder",
    alertEmailCritical: true,
    alertDailyLowStockDigest: true,
    alertPoDelayNotify: false,
    poDelayGraceDays: 2,

    allowNegativeStock: false,
    inventoryLockedThrough: null,

    allowGrnExcessReceipt: false,
    grnExcessTolerancePct: 0,

    requirePoApprovalAbove: 100000,
    requireMakerChecker: false,

    variancePriceTolerancePct: 1,
    varianceAmountTolerance: 500,

    numbering: {
      rfq: { prefix: "RFQ-2026-", padding: 5 },
      po: { prefix: "PO-2026-", padding: 5 },
      grn: { prefix: "GRN-2026-", padding: 5 },
      proforma: { prefix: "PI-2026-", padding: 5 },
      invoice: { prefix: "SI-2026-", padding: 5 },
      transfer: { prefix: "TRF-2026-", padding: 5 },
      return: { prefix: "PR-2026-", padding: 5 },
      adjustment: { prefix: "ADJ-2026-", padding: 5 },
    },
  },
];

export const documentSequences: DocumentSequence[] = [
  { id: "seq_rfq", docType: "rfq", financialYear: "2026-27", prefix: "RFQ-2026-", padding: 5, nextNumber: 59 },
  { id: "seq_po", docType: "po", financialYear: "2026-27", prefix: "PO-2026-", padding: 5, nextNumber: 125 },
  { id: "seq_grn", docType: "grn", financialYear: "2026-27", prefix: "GRN-2026-", padding: 5, nextNumber: 92 },
  { id: "seq_proforma", docType: "proforma", financialYear: "2026-27", prefix: "PI-2026-", padding: 5, nextNumber: 4 },
  { id: "seq_invoice", docType: "invoice", financialYear: "2026-27", prefix: "SI-2026-", padding: 5, nextNumber: 3 },
  { id: "seq_transfer", docType: "transfer", financialYear: "2026-27", prefix: "TRF-2026-", padding: 5, nextNumber: 35 },
  { id: "seq_return", docType: "return", financialYear: "2026-27", prefix: "PR-2026-", padding: 5, nextNumber: 2 },
  { id: "seq_adjustment", docType: "adjustment", financialYear: "2026-27", prefix: "ADJ-2026-", padding: 5, nextNumber: 8 },
];

/* ------------------------------------------------------------ RBAC ---- */

const ALL_VIEW: PermissionCode[] = [
  "dashboard.view", "product.view", "supplier.view", "godown.view", "inventory.view",
  "rfq.view", "quotation.view", "comparison.view", "po.view", "proforma.view",
  "grn.view", "invoice.view", "return.view", "document.view", "ai.view", "ai.assistant",
  "alert.view", "report.view", "master.view",
];

const OWNER_PERMISSIONS: PermissionCode[] = [
  ...ALL_VIEW,
  "product.create", "product.update", "product.delete", "product.import", "product.export",
  "master.manage",
  "supplier.create", "supplier.update", "supplier.delete", "supplier.export",
  "godown.manage",
  "inventory.view_all", "inventory.adjust", "inventory.transfer", "inventory.transfer_any",
  "inventory.override_expiry", "inventory.close_period", "inventory.export",
  "rfq.create", "rfq.update", "rfq.delete", "rfq.send", "rfq.cancel",
  "quotation.create", "quotation.update", "quotation.delete", "quotation.approve", "quotation.reject",
  "comparison.create", "comparison.decide", "comparison.convert",
  "po.create", "po.update", "po.delete_draft", "po.submit", "po.approve", "po.approve_high_value",
  "po.send", "po.cancel", "po.close",
  "proforma.create", "proforma.update", "proforma.approve", "proforma.approve_variance", "proforma.raise_query",
  "grn.create", "grn.update", "grn.confirm", "grn.reverse", "grn.receive_other_godown", "grn.allow_excess",
  "invoice.create", "invoice.update", "invoice.match", "invoice.approve", "invoice.dispute",
  "return.create", "return.confirm",
  "document.upload", "document.delete", "document.download",
  "ai.review", "ai.approve_extraction", "ai.manage_mappings",
  "alert.manage", "report.export",
  "user.view", "user.manage", "user.manage_owners",
  "company.view", "company.manage", "audit.view",
];

const PURCHASE_PERMISSIONS: PermissionCode[] = [
  ...ALL_VIEW,
  "product.create", "product.update", "product.import", "product.export",
  "supplier.create", "supplier.update", "supplier.export",
  "inventory.view_all", "inventory.export",
  "rfq.create", "rfq.update", "rfq.delete", "rfq.send", "rfq.cancel",
  "quotation.create", "quotation.update", "quotation.delete", "quotation.approve", "quotation.reject",
  "comparison.create", "comparison.decide", "comparison.convert",
  "po.create", "po.update", "po.delete_draft", "po.submit", "po.approve", "po.send", "po.cancel", "po.close",
  "proforma.approve", "proforma.raise_query",
  "return.create",
  "document.upload", "document.delete", "document.download",
  "ai.review", "ai.approve_extraction", "ai.manage_mappings",
  "alert.manage", "report.export", "user.view", "audit.view", "invoice.dispute",
];

const GODOWN_PERMISSIONS: PermissionCode[] = [
  ...ALL_VIEW,
  "product.create", "product.update",
  "godown.manage",
  "inventory.view_all", "inventory.adjust", "inventory.transfer", "inventory.export",
  "rfq.create",
  "grn.create", "grn.update", "grn.confirm", "grn.allow_excess",
  "return.create",
  "document.upload", "document.download",
  "alert.manage", "report.export", "user.view", "audit.view",
];

const ACCOUNTANT_PERMISSIONS: PermissionCode[] = [
  ...ALL_VIEW,
  "product.export", "supplier.export", "inventory.view_all", "inventory.export",
  "proforma.approve",
  "invoice.create", "invoice.update", "invoice.match", "invoice.approve", "invoice.dispute",
  "document.upload", "document.download",
  "ai.review", "ai.approve_extraction",
  "report.export", "audit.view",
];

const STAFF_PERMISSIONS: PermissionCode[] = [
  "dashboard.view", "product.view", "supplier.view", "godown.view", "inventory.view",
  "grn.view", "grn.create", "grn.update",
  "document.view", "document.upload", "ai.assistant", "alert.view",
];

const VIEWER_PERMISSIONS: PermissionCode[] = [...ALL_VIEW];

const PLATFORM_PERMISSIONS: PermissionCode[] = [
  "platform.companies.view", "platform.companies.manage", "platform.users.view",
  "platform.impersonate", "platform.activity.view",
];

export const roles: Role[] = [
  {
    id: ROLE.superAdmin, code: "super_admin", name: "Super Admin", isSystem: true,
    description: "Platform operator. Manages tenants; has no tenant-data permissions except through audited impersonation.",
    permissions: PLATFORM_PERMISSIONS,
  },
  { id: ROLE.owner, code: "owner", name: "Owner", isSystem: true, description: "Full access to this company.", permissions: OWNER_PERMISSIONS },
  { id: ROLE.purchase, code: "purchase_manager", name: "Purchase Manager", isSystem: true, description: "Sourcing, suppliers and purchase orders.", permissions: PURCHASE_PERMISSIONS },
  { id: ROLE.godown, code: "godown_manager", name: "Godown Manager", isSystem: true, description: "Receiving, stock movements and godown operations.", permissions: GODOWN_PERMISSIONS },
  { id: ROLE.accountant, code: "accountant", name: "Accountant", isSystem: true, description: "Proformas, supplier invoices and payables.", permissions: ACCOUNTANT_PERMISSIONS },
  { id: ROLE.staff, code: "staff", name: "Staff", isSystem: true, description: "Godown-scoped day-to-day operations.", permissions: STAFF_PERMISSIONS },
  { id: ROLE.viewer, code: "viewer", name: "Viewer", isSystem: true, description: "Read-only access for auditors and advisors.", permissions: VIEWER_PERMISSIONS },
];

export const users: User[] = [
  {
    id: USER.owner, companyId: COMPANY_ID, email: "useradmin@acmetraders.in", username: "useradmin",
    fullName: "Sharad", roleId: ROLE.owner, roleCode: "owner", status: "active",
    isPlatformAdmin: false, godownScope: { all: true, godownIds: [] },
    lastActiveAt: NOW, deletedAt: null,
  },
  {
    id: USER.platform, companyId: null, email: "superadmin@inventoryai.in", username: "superadmin",
    fullName: "Platform Admin", roleId: ROLE.superAdmin, roleCode: "super_admin", status: "active",
    isPlatformAdmin: true, godownScope: { all: false, godownIds: [] },
    lastActiveAt: NOW, deletedAt: null,
  },
  {
    id: USER.godownMgr, companyId: COMPANY_ID, email: "mahesh@acmetraders.in",
    fullName: "Mahesh Pawar", roleId: ROLE.godown, roleCode: "godown_manager", status: "active",
    isPlatformAdmin: false, godownScope: { all: false, godownIds: [GODOWN.secondary] },
    lastActiveAt: "2026-09-13T17:10:00+05:30", deletedAt: null,
  },
  {
    id: USER.purchaseMgr, companyId: COMPANY_ID, email: "anita@acmetraders.in",
    fullName: "Anita Deshpande", roleId: ROLE.purchase, roleCode: "purchase_manager", status: "active",
    isPlatformAdmin: false, godownScope: { all: true, godownIds: [] },
    lastActiveAt: "2026-09-12T12:02:00+05:30", deletedAt: null,
  },
  {
    id: USER.accountant, companyId: COMPANY_ID, email: "rajesh@acmetraders.in",
    fullName: "Rajesh Kulkarni", roleId: ROLE.accountant, roleCode: "accountant", status: "active",
    isPlatformAdmin: false, godownScope: { all: true, godownIds: [] },
    lastActiveAt: "2026-09-09T11:20:00+05:30", deletedAt: null,
  },
  {
    id: USER.staff, companyId: COMPANY_ID, email: "vikas@acmetraders.in",
    fullName: "Vikas Sharma", roleId: ROLE.staff, roleCode: "staff", status: "inactive",
    isPlatformAdmin: false, godownScope: { all: false, godownIds: [GODOWN.main] },
    lastActiveAt: "2026-08-28T09:45:00+05:30", deletedAt: null,
  },
  // Users belonging to other tenants — visible only to the platform admin.
  {
    id: "usr_ganesh_owner", companyId: "co_shree_ganesh", email: "owner@shreeganesh.in",
    fullName: "Ganesh Kulkarni", roleId: ROLE.owner, roleCode: "owner", status: "active",
    isPlatformAdmin: false, godownScope: { all: true, godownIds: [] }, deletedAt: null,
  },
  {
    id: "usr_konkan_owner", companyId: "co_konkan", email: "admin@konkanfoodmart.in",
    fullName: "Prasad Sawant", roleId: ROLE.owner, roleCode: "owner", status: "active",
    isPlatformAdmin: false, godownScope: { all: true, godownIds: [] }, deletedAt: null,
  },
  {
    id: "usr_bharat_owner", companyId: "co_bharat", email: "sales@bharatelectricals.in",
    fullName: "Nilesh Shah", roleId: ROLE.purchase, roleCode: "purchase_manager", status: "active",
    isPlatformAdmin: false, godownScope: { all: true, godownIds: [] }, deletedAt: null,
  },
  {
    id: "usr_deccan_owner", companyId: "co_deccan", email: "accounts@deccanauto.in",
    fullName: "Ravi Patil", roleId: ROLE.accountant, roleCode: "accountant", status: "inactive",
    isPlatformAdmin: false, godownScope: { all: true, godownIds: [] }, deletedAt: null,
  },
];

export const invitations: Invitation[] = [
  {
    id: "inv_priya",
    email: "priya@acmetraders.in",
    fullName: "Priya Nair",
    roleId: ROLE.staff,
    roleCode: "staff",
    godownScope: { all: false, godownIds: [GODOWN.main] },
    invitedBy: USER.owner,
    invitedByName: "Sharad",
    invitedAt: "2026-09-10T10:15:00+05:30",
    expiresAt: "2026-09-17T10:15:00+05:30",
    resendCount: 0,
    status: "pending",
  },
];

/** Credentials for the prototype's demo accounts. Never a real auth mechanism. */
export const demoCredentials = [
  { username: "useradmin", password: "useradmin", userId: USER.owner },
  { username: "superadmin", password: "superadmin", userId: USER.platform },
];
