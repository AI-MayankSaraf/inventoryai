/**
 * Types for the Supplier Portal.
 *
 * A supplier is master data inside the tenant app — it has no staff login
 * there. This portal is a separate identity (`supplier_portal_accounts`):
 * one supplier contact signs in once and sees every company on the platform
 * that granted them access, switching between them rather than holding a
 * separate account per company.
 */

/** One company this login may work in, as one of that company's suppliers. */
export interface SupplierPortalCompany {
  /** The access grant's id — what activity is fetched by. */
  id: string;
  companyId: string;
  name: string;
  city: string;
  stateName: string;
  supplierId: string;
  /** How this company knows you (its supplier record's name). */
  supplierName: string;
}

export interface SupplierPortalPrincipal {
  id: string;
  contactName: string;
  email: string;
  companies: SupplierPortalCompany[];
}

export interface SupplierPortalRfqSummary {
  id: string;
  number: string;
  subject: string;
  date: string;
  expected: string | null;
  status: string;
  /** Where your reply stands on this RFQ: sent, quoted, declined… */
  invitationStatus: string;
  lineCount: number;
}

export interface SupplierPortalQuotationSummary {
  id: string;
  number: string;
  rfqNumber: string;
  date: string | null;
  validUntil: string | null;
  status: string;
  totalAmount: number;
}

export interface SupplierPortalPoSummary {
  id: string;
  number: string;
  date: string;
  expected: string | null;
  status: string;
  lineCount: number;
  /** Including GST and charges. */
  totalAmount: number;
}

export interface SupplierPortalCompanyActivity {
  rfqs: SupplierPortalRfqSummary[];
  quotations: SupplierPortalQuotationSummary[];
  purchaseOrders: SupplierPortalPoSummary[];
}

/** A company's view of who can sign in as one of its suppliers. */
export interface SupplierPortalAccess {
  id: string;
  accountId: string;
  email: string;
  fullName: string;
  /** `active` or `revoked` — this company's grant. */
  status: "active" | "revoked";
  /** `invited` until they set a password, then `active`. */
  accountStatus: "invited" | "active" | "disabled";
  grantedAt: string;
  lastLoginAt: string | null;
}
