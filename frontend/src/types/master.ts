/** Tenancy, identity, access control and master data. */

import type {
  AuditFields,
  DateOnly,
  Id,
  Money,
  Percent,
  Quantity,
  RoundingMode,
  SoftDeletable,
  Timestamp,
} from "./common";

/* ------------------------------------------------------------- Tenancy */

export type CompanyPlan = "Trial" | "Starter" | "Growth" | "Enterprise";
export type CompanyStatus = "active" | "suspended";

export interface Company {
  id: Id;
  name: string;
  legalName?: string;
  gstin: string | null;
  pan: string | null;
  /** 2-digit GST state code — decides IGST vs CGST/SGST on every document. */
  stateCode: string;
  stateName: string;
  city: string;
  addressLine1: string;
  addressLine2?: string;
  pincode?: string;
  email?: string;
  phone?: string;
  plan: CompanyPlan;
  status: CompanyStatus;
  suspendedAt?: Timestamp | null;
  suspendedReason?: string | null;
  onboardedOn: DateOnly;
  ownerEmail: string;
}

export interface NumberingConfig {
  prefix: string;
  padding: number;
}

export type DocSequenceType =
  | "rfq"
  | "po"
  | "grn"
  | "proforma"
  | "invoice"
  | "transfer"
  | "return"
  | "adjustment";

export interface DocumentSequence {
  id: Id;
  docType: DocSequenceType;
  financialYear: string;
  prefix: string;
  padding: number;
  nextNumber: number;
}

/** Everything on the Settings screen. 1:1 with the tenant. */
export interface CompanySettings {
  id: Id;
  companyId: Id;
  currencyCode: string;
  defaultGstRate: Percent;
  roundingMode: RoundingMode;
  financialYearStartMonth: number;
  defaultGodownId: Id | null;

  // AI behaviour
  aiAutoProcess: boolean;
  aiReviewConfidenceThreshold: Percent;
  aiSuggestWhileTyping: boolean;
  /** Locked on — the backend enforces it too (BR-AI-02). */
  aiNeverAutoApproveFinancials: true;

  // Alerts
  lowStockThresholdMode: "reorder" | "110" | "125";
  alertEmailCritical: boolean;
  alertDailyLowStockDigest: boolean;
  alertPoDelayNotify: boolean;
  poDelayGraceDays: number;

  // Inventory policy
  allowNegativeStock: boolean;
  inventoryLockedThrough: DateOnly | null;

  // Receiving policy
  allowGrnExcessReceipt: boolean;
  grnExcessTolerancePct: Percent;

  // Approvals
  requirePoApprovalAbove: Money | null;
  requireMakerChecker: boolean;

  // Variance tolerance
  variancePriceTolerancePct: Percent;
  varianceAmountTolerance: Money;

  // Document numbering, per document type
  numbering: Record<DocSequenceType, NumberingConfig>;
}

/* -------------------------------------------------------------- Identity */

export type RoleCode =
  | "super_admin"
  | "owner"
  | "purchase_manager"
  | "godown_manager"
  | "accountant"
  | "staff"
  | "viewer";

/**
 * Permission codes from `07_RBAC_MATRIX.md`. The UI checks permissions, never
 * role names, so a custom role can be added without touching screen code.
 *
 * NOTE: this drives UX only. Real enforcement is server-side (C5).
 */
export type PermissionCode =
  | "dashboard.view"
  | "product.view" | "product.create" | "product.update" | "product.delete" | "product.import" | "product.export"
  | "master.view" | "master.manage"
  | "supplier.view" | "supplier.create" | "supplier.update" | "supplier.delete" | "supplier.export"
  | "godown.view" | "godown.manage"
  | "inventory.view" | "inventory.view_all" | "inventory.adjust" | "inventory.transfer"
  | "inventory.transfer_any" | "inventory.override_expiry" | "inventory.close_period" | "inventory.export"
  | "rfq.view" | "rfq.create" | "rfq.update" | "rfq.delete" | "rfq.send" | "rfq.cancel" | "rfq.import"
  | "quotation.view" | "quotation.create" | "quotation.update" | "quotation.delete" | "quotation.approve" | "quotation.reject"
  | "comparison.view" | "comparison.create" | "comparison.decide" | "comparison.convert"
  | "po.view" | "po.create" | "po.update" | "po.delete_draft" | "po.submit" | "po.approve"
  | "po.approve_high_value" | "po.send" | "po.cancel" | "po.close"
  | "proforma.view" | "proforma.create" | "proforma.update" | "proforma.approve" | "proforma.approve_variance" | "proforma.raise_query"
  | "grn.view" | "grn.create" | "grn.update" | "grn.confirm" | "grn.reverse" | "grn.receive_other_godown" | "grn.allow_excess"
  | "invoice.view" | "invoice.create" | "invoice.update" | "invoice.match" | "invoice.approve" | "invoice.dispute"
  | "return.view" | "return.create" | "return.confirm"
  | "document.view" | "document.upload" | "document.delete" | "document.download"
  | "ai.view" | "ai.review" | "ai.approve_extraction" | "ai.manage_mappings" | "ai.assistant"
  | "alert.view" | "alert.manage"
  | "report.view" | "report.export"
  | "user.view" | "user.manage" | "user.manage_owners"
  | "company.view" | "company.manage"
  | "audit.view"
  | "platform.companies.view" | "platform.companies.manage" | "platform.users.view"
  | "platform.impersonate" | "platform.activity.view";

export interface Role {
  id: Id;
  code: RoleCode;
  name: string;
  description?: string;
  isSystem: boolean;
  permissions: PermissionCode[];
}

export type UserStatus = "invited" | "active" | "inactive" | "suspended";

/** Which godowns a user may see and act in (BR-AUTH-12). */
export interface GodownScope {
  all: boolean;
  godownIds: Id[];
}

export interface User {
  id: Id;
  /** NULL ⇒ platform (Super) admin, who has no tenant data permissions. */
  companyId: Id | null;
  email: string;
  username?: string;
  fullName: string;
  phone?: string;
  roleId: Id;
  roleCode: RoleCode;
  status: UserStatus;
  isPlatformAdmin: boolean;
  godownScope: GodownScope;
  avatarUrl?: string;
  lastActiveAt?: Timestamp;
  deletedAt: Timestamp | null;
}

/** The authenticated principal the UI reasons about. */
export interface SessionUser extends User {
  companyName: string;
  roleName: string;
  permissions: PermissionCode[];
  /**
   * BR-AUTH-13. `companyId` above is the company this session is *acting
   * in*; this is where the user's own record lives. They differ only after
   * switching into another company from the header.
   */
  homeCompanyId?: Id | null;
}

/** One entry in the header's company switcher (`GET /auth/me/companies`). */
export interface CompanyMembership {
  companyId: Id;
  companyName: string;
  companyStatus: "active" | "suspended";
  roleCode: string;
  roleName: string;
  isHome: boolean;
  isCurrent: boolean;
}

export type InvitationStatus = "pending" | "accepted" | "revoked" | "expired";

export interface Invitation {
  id: Id;
  email: string;
  fullName: string;
  roleId: Id;
  roleCode: RoleCode;
  godownScope: GodownScope;
  invitedBy: Id;
  invitedByName: string;
  invitedAt: Timestamp;
  expiresAt: Timestamp;
  resendCount: number;
  lastSentAt?: Timestamp;
  status: InvitationStatus;
  acceptedAt?: Timestamp;
  acceptedUserId?: Id;
  /** Only set right after invite/resend, and only in development — the
   * backend returns the raw token there and nowhere else. */
  inviteLink?: string;
}

export interface ImpersonationSession {
  id: Id;
  platformUserId: Id;
  platformUserName: string;
  targetUserId: Id;
  targetUserName: string;
  targetCompanyId: Id;
  targetCompanyName: string;
  reason: string;
  startedAt: Timestamp;
  expiresAt: Timestamp;
  endedAt?: Timestamp | null;
}

/* ---------------------------------------------------------- Master data */

export interface Category extends SoftDeletable {
  id: Id;
  parentId: Id | null;
  name: string;
  code?: string;
  /** Denormalised breadcrumb, e.g. `Home Appliances/Cookware`. */
  path: string;
}

export interface Brand extends SoftDeletable {
  id: Id;
  name: string;
  code?: string;
  manufacturerName?: string;
}

export type UomType = "count" | "weight" | "volume" | "length";

export interface Uom {
  id: Id;
  code: string;
  name: string;
  uomType: UomType;
  decimalPlaces: number;
  isActive: boolean;
}

/** How many base units one alternate unit contains, per variant (I10). */
export interface ProductUomConversion {
  id: Id;
  productVariantId: Id;
  fromUomId: Id;
  toUomId: Id;
  factor: number;
  isPurchaseDefault: boolean;
}

export type TrackingType = "none" | "batch" | "serial";

/**
 * The catalogue item — what a buyer talks about. Stock never attaches here:
 * it belongs to the variant, and only ever as a sum of transactions (C2).
 */
export interface Product extends SoftDeletable, AuditFields {
  id: Id;
  name: string;
  slug?: string;
  brandId: Id | null;
  categoryId: Id | null;
  manufacturerName?: string;
  description?: string;
  hsnCode: string;
  gstRate: Percent;
  cessRate: Percent;
  trackingType: TrackingType;
  baseUomId: Id;
  displayEmoji?: string;
}

/**
 * The stockable, orderable, priced unit — **this is the SKU**. Everything in
 * inventory and procurement references `productVariantId`, never `productId`.
 */
export interface ProductVariant extends SoftDeletable, AuditFields {
  id: Id;
  productId: Id;
  sku: string;
  variantName?: string;
  barcode?: string;
  ean?: string;
  upc?: string;
  mpn?: string;
  modelCode?: string;
  hsnCode?: string;
  gstRate?: Percent;
  uomId: Id;
  packSize?: number;
  purchasePrice: Money;
  salePrice: Money;
  mrp: Money;
  reorderPoint: Quantity;
  reorderQty: Quantity;
  leadTimeDays?: number;
  attributes: Record<string, string>;
  /** Normalised text the matcher searches. Server-generated in production. */
  searchText?: string;
}

export interface ProductImage {
  id: Id;
  productId: Id;
  productVariantId?: Id | null;
  documentId: Id;
  sortOrder: number;
  isPrimary: boolean;
}

/** Per-godown reorder policy (optional override of the variant's default). */
export interface StockPolicy {
  id: Id;
  productVariantId: Id;
  godownId: Id;
  reorderPoint: Quantity;
  reorderQty: Quantity;
  maxStock?: Quantity;
  isStocked: boolean;
}

/* --------------------------------------------------------------- Godown */

export interface Godown extends SoftDeletable, AuditFields {
  id: Id;
  name: string;
  code?: string;
  city: string;
  stateCode: string;
  address?: string;
  gstin?: string | null;
  inchargeUserId: Id | null;
  inchargeName?: string;
  capacityValue?: number;
  capacityUomId?: Id | null;
  isDefault: boolean;
}

/* ------------------------------------------------------------ Suppliers */

export type SupplierType = "Manufacturer" | "Distributor" | "Online" | "Local Supplier" | "Importer";
export type GstTreatment = "regular" | "composition" | "unregistered" | "overseas";
export type SupplierStatus = "active" | "inactive";

export interface Supplier extends SoftDeletable, AuditFields {
  id: Id;
  name: string;
  supplierCode?: string;
  gstin: string | null;
  pan: string | null;
  gstTreatment: GstTreatment;
  supplierType: SupplierType;
  city: string;
  stateCode: string;
  stateName: string;
  address: string;
  pincode?: string;
  primaryContactName: string;
  phone: string;
  email: string;
  paymentTerms: string;
  paymentTermsDays?: number;
  bankName?: string;
  bankAccountNo?: string;
  bankIfsc?: string;
  status: SupplierStatus;
  notes?: string;
}

export interface SupplierContact {
  id: Id;
  supplierId: Id;
  name: string;
  designation: string;
  phone: string;
  email: string;
  isPrimary: boolean;
}

/**
 * The supplier's own code and price for one of our SKUs. Confirming an AI
 * match writes one of these, which is what makes matching converge (BR-AI-06).
 */
export interface SupplierProduct {
  id: Id;
  supplierId: Id;
  productVariantId: Id;
  supplierSku?: string;
  supplierDescription?: string;
  supplierUomId?: Id;
  conversionToBase: number;
  lastQuotedPrice?: Money;
  lastQuotedAt?: DateOnly;
  lastPurchasePrice?: Money;
  lastPurchaseAt?: DateOnly;
  leadTimeDays?: number;
  isPreferred: boolean;
  /** `purchase_history`: derived from approved POs — nobody has recorded
   * this supplier's own item code yet, so there is no link row (C-phase). */
  matchSource: "manual" | "ai_confirmed" | "imported" | "purchase_history";
  confirmedBy?: Id;
  confirmedAt?: Timestamp;
}

/** Derived supplier analytics — computed by the service, never stored (I17). */
export interface SupplierPerformance {
  supplierId: Id;
  productsSupplied: number;
  totalPurchases: Money;
  openOrders: number;
  onTimeDeliveryPct: Percent;
  qualityScorePct: Percent;
  openVariances: number;
}
