/**
 * The complete seeded dataset, assembled into one object shaped like the
 * database in `02_DATABASE_DESIGN.md`.
 *
 * Everything downstream — repositories, services, hooks, screens — reads this
 * shape and nothing else. When the real backend lands, the API client stops
 * calling the repository and starts calling HTTP; the shapes do not change.
 */

import type {
  Alert,
  AlertRule,
  AiExtractedField,
  AiExtractedLine,
  AiExtractionResult,
  AiMatchCandidate,
  AiProcessingJob,
  AiReviewAction,
  AuditLog,
  Batch,
  Brand,
  CanonicalField,
  Category,
  Company,
  CompanySettings,
  DocumentLink,
  DocumentSchemaMapping,
  DocumentSchemaMappingField,
  DocumentSequence,
  DocumentVariance,
  Godown,
  GoodsReceipt,
  GoodsReceiptItem,
  InventoryTransaction,
  Invitation,
  OutboundMessage,
  ProductUomConversion,
  Product,
  ProductVariant,
  ProformaInvoice,
  ProformaInvoiceItem,
  PurchaseOrder,
  PurchaseOrderItem,
  PurchaseReturn,
  PurchaseReturnItem,
  QuotationComparison,
  QuotationComparisonLine,
  ReportDefinition,
  Rfq,
  RfqItem,
  RfqSupplier,
  Role,
  StockBalance,
  StockPolicy,
  StockTransfer,
  StockTransferItem,
  StoredDocument,
  Supplier,
  SupplierContact,
  SupplierInvoice,
  SupplierInvoiceItem,
  SupplierProduct,
  SupplierQuotation,
  SupplierQuotationItem,
  Uom,
  User,
} from "@/types";

import * as catalog from "./catalog";
import * as docs from "./documents";
import * as inventory from "./inventory";
import * as ops from "./ops";
import * as procurement from "./procurement";
import * as suppliers from "./suppliers";
import * as tenancy from "./tenancy";

export interface MockDatabase {
  /* tenancy and access */
  companies: Company[];
  companySettings: CompanySettings[];
  documentSequences: DocumentSequence[];
  roles: Role[];
  users: User[];
  invitations: Invitation[];

  /* master data */
  uoms: Uom[];
  categories: Category[];
  brands: Brand[];
  godowns: Godown[];
  products: Product[];
  productVariants: ProductVariant[];
  productUomConversions: ProductUomConversion[];
  stockPolicies: StockPolicy[];
  suppliers: Supplier[];
  supplierContacts: SupplierContact[];
  supplierProducts: SupplierProduct[];

  /* inventory */
  batches: Batch[];
  inventoryTransactions: InventoryTransaction[];
  stockBalances: StockBalance[];
  stockTransfers: StockTransfer[];
  stockTransferItems: StockTransferItem[];

  /* procurement */
  rfqs: Rfq[];
  rfqItems: RfqItem[];
  rfqSuppliers: RfqSupplier[];
  supplierQuotations: SupplierQuotation[];
  supplierQuotationItems: SupplierQuotationItem[];
  quotationComparisons: QuotationComparison[];
  quotationComparisonLines: QuotationComparisonLine[];
  purchaseOrders: PurchaseOrder[];
  purchaseOrderItems: PurchaseOrderItem[];
  proformaInvoices: ProformaInvoice[];
  proformaInvoiceItems: ProformaInvoiceItem[];
  goodsReceipts: GoodsReceipt[];
  goodsReceiptItems: GoodsReceiptItem[];
  supplierInvoices: SupplierInvoice[];
  supplierInvoiceItems: SupplierInvoiceItem[];
  purchaseReturns: PurchaseReturn[];
  purchaseReturnItems: PurchaseReturnItem[];
  documentVariances: DocumentVariance[];

  /* documents and AI */
  storedDocuments: StoredDocument[];
  documentLinks: DocumentLink[];
  aiProcessingJobs: AiProcessingJob[];
  aiExtractionResults: AiExtractionResult[];
  aiExtractedFields: AiExtractedField[];
  aiExtractedLines: AiExtractedLine[];
  aiMatchCandidates: AiMatchCandidate[];
  aiReviewActions: AiReviewAction[];
  canonicalFields: CanonicalField[];
  documentSchemaMappings: DocumentSchemaMapping[];
  documentSchemaMappingFields: DocumentSchemaMappingField[];

  /* ops */
  alerts: Alert[];
  alertRules: AlertRule[];
  auditLogs: AuditLog[];
  reportDefinitions: ReportDefinition[];
  outboundMessages: OutboundMessage[];
}

/** A fresh copy of the seed. Callers mutate their copy, never this function's source. */
export function createSeedDatabase(): MockDatabase {
  return structuredClone({
    companies: tenancy.companies,
    companySettings: tenancy.companySettings,
    documentSequences: tenancy.documentSequences,
    roles: tenancy.roles,
    users: tenancy.users,
    invitations: tenancy.invitations,

    uoms: catalog.uoms,
    categories: catalog.categories,
    brands: catalog.brands,
    godowns: catalog.godowns,
    products: catalog.products,
    productVariants: catalog.productVariants,
    productUomConversions: catalog.productUomConversions,
    stockPolicies: catalog.stockPolicies,
    suppliers: suppliers.suppliers,
    supplierContacts: suppliers.supplierContacts,
    supplierProducts: suppliers.supplierProducts,

    batches: inventory.batches,
    inventoryTransactions: inventory.inventoryTransactions,
    stockBalances: inventory.stockBalances,
    stockTransfers: inventory.stockTransfers,
    stockTransferItems: inventory.stockTransferItems,

    rfqs: procurement.rfqs,
    rfqItems: procurement.rfqItems,
    rfqSuppliers: procurement.rfqSuppliers,
    supplierQuotations: procurement.supplierQuotations,
    supplierQuotationItems: procurement.supplierQuotationItems,
    quotationComparisons: procurement.quotationComparisons,
    quotationComparisonLines: procurement.quotationComparisonLines,
    purchaseOrders: procurement.purchaseOrders,
    purchaseOrderItems: procurement.purchaseOrderItems,
    proformaInvoices: procurement.proformaInvoices,
    proformaInvoiceItems: procurement.proformaInvoiceItems,
    goodsReceipts: procurement.goodsReceipts,
    goodsReceiptItems: procurement.goodsReceiptItems,
    supplierInvoices: procurement.supplierInvoices,
    supplierInvoiceItems: procurement.supplierInvoiceItems,
    purchaseReturns: procurement.purchaseReturns,
    purchaseReturnItems: procurement.purchaseReturnItems,
    documentVariances: procurement.documentVariances,

    storedDocuments: docs.storedDocuments,
    documentLinks: docs.documentLinks,
    aiProcessingJobs: docs.aiProcessingJobs,
    aiExtractionResults: docs.aiExtractionResults,
    aiExtractedFields: docs.aiExtractedFields,
    aiExtractedLines: docs.aiExtractedLines,
    aiMatchCandidates: docs.aiMatchCandidates,
    aiReviewActions: docs.aiReviewActions,
    canonicalFields: docs.canonicalFields,
    documentSchemaMappings: docs.documentSchemaMappings,
    documentSchemaMappingFields: docs.documentSchemaMappingFields,

    alerts: ops.alerts,
    alertRules: ops.alertRules,
    auditLogs: ops.auditLogs,
    reportDefinitions: ops.reportDefinitions,
    outboundMessages: ops.outboundMessages,
  } satisfies MockDatabase);
}

export { demoCredentials } from "./tenancy";
export { deriveStockBalances } from "./inventory";
