/**
 * Alerts, alert rules, the audit log, report definitions and the outbound
 * message log.
 *
 * Alerts are rule outputs, not things a component decides to show. Each one
 * names the `ruleCode` that produced it and points at a real record by id, so
 * the browser never has to invent an alert from data it happens to be holding
 * (BR-ALT-01, I13).
 */

import type { Alert, AlertRule, AuditLog, OutboundMessage, ReportDefinition } from "@/types";
import {
  GODOWN,
  GRN,
  PO,
  PURCHASE_RETURN,
  QUOTE,
  RFQ,
  SUPPLIER,
  SUPPLIER_INVOICE,
  USER,
  variantId,
} from "../ids";

export const alertRules: AlertRule[] = [
  { ruleCode: "LOW_STOCK_BELOW_REORDER", label: "Stock below reorder point", description: "Raised when a variant's balance in a godown falls to or below its reorder point.", isEnabled: true, severity: "medium", notifyEmail: true, notifyInApp: true },
  { ruleCode: "OUT_OF_STOCK", label: "Out of stock", description: "Raised when a stocked variant reaches zero in a godown.", isEnabled: true, severity: "high", notifyEmail: true, notifyInApp: true },
  { ruleCode: "GRN_QTY_MISMATCH", label: "Receipt quantity mismatch", description: "Received quantity differs from the ordered quantity on a confirmed GRN.", isEnabled: true, severity: "high", notifyEmail: true, notifyInApp: true },
  { ruleCode: "GRN_WRONG_PRODUCT", label: "Wrong product received", description: "A GRN line was flagged as wrong product, variant, model or brand.", isEnabled: true, severity: "critical", notifyEmail: true, notifyInApp: true },
  { ruleCode: "PROFORMA_VARIANCE", label: "Proforma differs from PO", description: "A proforma rate or total exceeds the PO by more than the tolerance.", isEnabled: true, severity: "high", notifyEmail: true, notifyInApp: true, thresholdConfig: { pricePct: 2 } },
  { ruleCode: "INVOICE_VARIANCE", label: "Invoice fails three-way match", description: "Invoice price or quantity does not agree with the PO and the GRN.", isEnabled: true, severity: "critical", notifyEmail: true, notifyInApp: true, thresholdConfig: { pricePct: 1, qtyPct: 0 } },
  { ruleCode: "PO_DELIVERY_DELAYED", label: "Delivery overdue", description: "A sent PO has passed its expected delivery date without full receipt.", isEnabled: true, severity: "medium", notifyEmail: false, notifyInApp: true, thresholdConfig: { graceDays: 2 } },
  { ruleCode: "QUOTATION_EXPIRING", label: "Quotation expiring", description: "A quotation under review is within three days of its validity date.", isEnabled: true, severity: "low", notifyEmail: false, notifyInApp: true, thresholdConfig: { days: 3 } },
  { ruleCode: "AI_LOW_CONFIDENCE", label: "AI extraction needs review", description: "An extraction finished below the auto-approve confidence threshold.", isEnabled: true, severity: "medium", notifyEmail: false, notifyInApp: true, thresholdConfig: { confidence: 85 } },
  { ruleCode: "DOCUMENT_UNREADABLE", label: "Document could not be read", description: "Extraction failed after the configured number of retries.", isEnabled: true, severity: "medium", notifyEmail: false, notifyInApp: true },
  { ruleCode: "BATCH_EXPIRING", label: "Batch nearing expiry", description: "A batch in stock expires within the configured window.", isEnabled: true, severity: "high", notifyEmail: true, notifyInApp: true, thresholdConfig: { days: 60 } },
  { ruleCode: "STOCK_BALANCE_DRIFT", label: "Balance drift detected", description: "A cached balance disagrees with the sum of its ledger rows.", isEnabled: true, severity: "critical", notifyEmail: true, notifyInApp: true },
];

export const alerts: Alert[] = [
  {
    id: "alt_1", ruleCode: "INVOICE_VARIANCE", severity: "critical", category: "Procurement",
    title: "Invoice AEC/2026/2210 fails three-way match",
    description: "Ceiling fans billed at ₹1,680 against a PO rate of ₹1,620, and 40 billed against 38 accepted.",
    referenceType: "supplier_invoice", referenceId: SUPPLIER_INVOICE.ahmedabad,
    referenceLabel: "AEC/2026/2210", deepLink: `/supplier-invoices/${SUPPLIER_INVOICE.ahmedabad}`,
    godownId: GODOWN.main, varianceId: "var_3", status: "new", occurrenceCount: 2,
    lastOccurredAt: "2026-09-09T15:06:00+05:30", createdAt: "2026-09-09T15:06:00+05:30",
    isRead: false,
  },
  {
    id: "alt_2", ruleCode: "GRN_QTY_MISMATCH", severity: "high", category: "Goods Receipt",
    title: "GRN-2026-00088 short by 2 units",
    description: "LG Refrigerator 260L — 8 received against 10 ordered on PO-2026-00122.",
    referenceType: "goods_receipt", referenceId: GRN.lg88, referenceLabel: "GRN-2026-00088",
    deepLink: `/goods-receipt/${GRN.lg88}`, godownId: GODOWN.main, varianceId: "var_2",
    status: "acknowledged", occurrenceCount: 1, lastOccurredAt: "2026-09-15T17:46:00+05:30",
    createdAt: "2026-09-15T17:46:00+05:30", isRead: true,
  },
  {
    id: "alt_3", ruleCode: "OUT_OF_STOCK", severity: "high", category: "Inventory",
    title: "Bajaj Water Heater 15L is out of stock",
    description: "Main Godown balance reached zero after the counter sale on 02 Sep.",
    referenceType: "product_variant", referenceId: variantId("SKU041"), referenceLabel: "SKU041",
    deepLink: "/inventory?godown=main&status=out_of_stock", godownId: GODOWN.main,
    status: "new", occurrenceCount: 1, lastOccurredAt: "2026-09-02T11:21:00+05:30",
    createdAt: "2026-09-02T11:21:00+05:30", isRead: false,
  },
  {
    id: "alt_4", ruleCode: "OUT_OF_STOCK", severity: "high", category: "Inventory",
    title: "Haldiram Namkeen 200g is out of stock at Secondary Godown",
    description: "Batch HLD/26/0301 expired and was written off, leaving no stock.",
    referenceType: "product_variant", referenceId: variantId("SKU005"), referenceLabel: "SKU005",
    deepLink: "/inventory?godown=secondary&status=out_of_stock", godownId: GODOWN.secondary,
    status: "new", occurrenceCount: 1, lastOccurredAt: "2026-09-03T10:01:00+05:30",
    createdAt: "2026-09-03T10:01:00+05:30", isRead: false,
  },
  {
    id: "alt_5", ruleCode: "LOW_STOCK_BELOW_REORDER", severity: "medium", category: "Inventory",
    title: "3 items at or below reorder point",
    description: "Pigeon Cooker 5L, Philips Mixer Grinder 750W and LG Refrigerator 260L need replenishment at Main Godown.",
    referenceType: "report", referenceId: "low_stock", referenceLabel: "Low stock",
    deepLink: "/inventory/low-stock", godownId: GODOWN.main, status: "new",
    occurrenceCount: 4, lastOccurredAt: "2026-09-13T06:00:00+05:30",
    createdAt: "2026-09-05T06:00:00+05:30", isRead: false,
  },
  {
    id: "alt_6", ruleCode: "PROFORMA_VARIANCE", severity: "high", category: "Procurement",
    title: "Proforma RR/PI/2026/0413 exceeds PO-2026-00123",
    description: "Refrigerator quoted at ₹25,000 against a PO rate of ₹24,500 (+2.04%).",
    referenceType: "proforma_invoice", referenceId: "pi_00041", referenceLabel: "RR/PI/2026/0413",
    deepLink: "/proforma/pi_00041", varianceId: "var_1", status: "acknowledged",
    occurrenceCount: 1, lastOccurredAt: "2026-09-11T14:20:00+05:30",
    createdAt: "2026-09-11T14:20:00+05:30", isRead: true,
  },
  {
    id: "alt_7", ruleCode: "AI_LOW_CONFIDENCE", severity: "medium", category: "AI Documents",
    title: "Rate list from Shree Balaji Traders needs review",
    description: "Extraction finished at 71% confidence with 2 unmatched lines.",
    referenceType: "document", referenceId: "doc_rate_balaji", referenceLabel: "balaji_rate_list.jpg",
    deepLink: "/ai-documents/review/doc_rate_balaji", status: "new", occurrenceCount: 1,
    lastOccurredAt: "2026-09-13T10:32:20+05:30", createdAt: "2026-09-13T10:32:20+05:30",
    isRead: false,
  },
  {
    id: "alt_8", ruleCode: "DOCUMENT_UNREADABLE", severity: "medium", category: "AI Documents",
    title: "scan_20260911_indore.png could not be read",
    description: "Three extraction attempts failed — image resolution too low.",
    referenceType: "document", referenceId: "doc_scan_unreadable",
    referenceLabel: "scan_20260911_indore.png", deepLink: "/ai-documents",
    status: "dismissed", occurrenceCount: 3, lastOccurredAt: "2026-09-11T18:14:34+05:30",
    createdAt: "2026-09-11T18:14:34+05:30", dismissedAt: "2026-09-12T09:15:00+05:30",
    isRead: true,
  },
  {
    id: "alt_9", ruleCode: "QUOTATION_EXPIRING", severity: "low", category: "Procurement",
    title: "Flipkart quotation FK/QTN/8821 expires in 3 days",
    description: "Valid until 21 Sep 2026 and still under review.",
    referenceType: "supplier_quotation", referenceId: QUOTE.flipkart, referenceLabel: "FK/QTN/8821",
    deepLink: `/quotations/${QUOTE.flipkart}`, status: "new", occurrenceCount: 1,
    lastOccurredAt: "2026-09-18T06:00:00+05:30", createdAt: "2026-09-18T06:00:00+05:30",
    isRead: false,
  },
  {
    id: "alt_10", ruleCode: "BATCH_EXPIRING", severity: "high", category: "Inventory",
    title: "Batch HLD/26/0722 expires in 69 days",
    description: "180 packs of Haldiram Namkeen 200g at Main Godown expire on 22 Nov 2026.",
    referenceType: "batch", referenceId: "bat_nam_0722", referenceLabel: "HLD/26/0722",
    deepLink: "/inventory?batch=bat_nam_0722", godownId: GODOWN.main, status: "new",
    occurrenceCount: 1, lastOccurredAt: "2026-09-14T06:00:00+05:30",
    createdAt: "2026-09-14T06:00:00+05:30", isRead: false,
  },
  {
    id: "alt_11", ruleCode: "PO_DELIVERY_DELAYED", severity: "medium", category: "Procurement",
    title: "PO-2026-00121 has no receipt yet",
    description: "Whirlpool washing machines were due on 19 Sep 2026.",
    referenceType: "purchase_order", referenceId: PO.whirlpool121, referenceLabel: "PO-2026-00121",
    deepLink: `/purchase-orders/${PO.whirlpool121}`, status: "new", occurrenceCount: 1,
    lastOccurredAt: "2026-09-21T06:00:00+05:30", createdAt: "2026-09-21T06:00:00+05:30",
    isRead: false,
  },
  {
    id: "alt_12", ruleCode: "GRN_WRONG_PRODUCT", severity: "critical", category: "Goods Receipt",
    title: "2 damaged fans quarantined on GRN-2026-00089",
    description: "Two Havells 1200mm fans arrived dented and were returned on PR-2026-00007.",
    referenceType: "goods_receipt", referenceId: GRN.ahmedabad89, referenceLabel: "GRN-2026-00089",
    deepLink: `/goods-receipt/${GRN.ahmedabad89}`, godownId: GODOWN.main, status: "resolved",
    occurrenceCount: 1, lastOccurredAt: "2026-09-08T17:46:00+05:30",
    createdAt: "2026-09-08T17:46:00+05:30", resolvedAt: "2026-09-10T12:16:00+05:30",
    isRead: true,
  },
];

/* ------------------------------------------------------------ Audit log */

export const auditLogs: AuditLog[] = [
  { id: "aud_1", entityType: "purchase_order", entityId: PO.reliance123, entityLabel: "PO-2026-00123", action: "created", actorUserId: USER.purchaseMgr, actorName: "Anita Deshpande", actorRole: "Purchase Manager", createdAt: "2026-09-10T12:00:00+05:30" },
  { id: "aud_2", entityType: "purchase_order", entityId: PO.reliance123, entityLabel: "PO-2026-00123", action: "approved", description: "Approved — within the ₹5,00,000 delegation", actorUserId: USER.owner, actorName: "Sharad", actorRole: "Owner", createdAt: "2026-09-10T15:20:00+05:30" },
  { id: "aud_3", entityType: "purchase_order", entityId: PO.reliance123, entityLabel: "PO-2026-00123", action: "sent", description: "Emailed to b2b@reliance.example", actorUserId: USER.purchaseMgr, actorName: "Anita Deshpande", actorRole: "Purchase Manager", createdAt: "2026-09-10T16:00:00+05:30" },
  { id: "aud_4", entityType: "goods_receipt", entityId: GRN.ahmedabad89, entityLabel: "GRN-2026-00089", action: "confirmed", description: "Posted 4 inventory transactions to Main Godown", actorUserId: USER.godownMgr, actorName: "Mahesh Pawar", actorRole: "Godown Manager", createdAt: "2026-09-08T17:45:00+05:30" },
  { id: "aud_5", entityType: "purchase_return", entityId: PURCHASE_RETURN.ahmedabad, entityLabel: "PR-2026-00007", action: "confirmed", description: "2 units returned; stock reduced at Main Godown", actorUserId: USER.godownMgr, actorName: "Mahesh Pawar", actorRole: "Godown Manager", createdAt: "2026-09-10T12:15:00+05:30" },
  { id: "aud_6", entityType: "supplier_invoice", entityId: SUPPLIER_INVOICE.ahmedabad, entityLabel: "AEC/2026/2210", action: "status_changed", description: "Marked disputed after the three-way match failed", beforeData: { status: "under_review" }, afterData: { status: "disputed" }, changedFields: ["status"], actorUserId: USER.accountant, actorName: "Rajesh Kulkarni", actorRole: "Accountant", createdAt: "2026-09-09T16:30:00+05:30" },
  { id: "aud_7", entityType: "supplier_quotation", entityId: QUOTE.lg, entityLabel: "LG-Q-556102", action: "approved", actorUserId: USER.purchaseMgr, actorName: "Anita Deshpande", actorRole: "Purchase Manager", createdAt: "2026-09-12T16:10:00+05:30" },
  { id: "aud_8", entityType: "rfq", entityId: RFQ.electricals, entityLabel: "RFQ-2026-00056", action: "sent", description: "Sent to 2 suppliers", actorUserId: USER.purchaseMgr, actorName: "Anita Deshpande", actorRole: "Purchase Manager", createdAt: "2026-09-08T11:30:00+05:30" },
  { id: "aud_9", entityType: "product_variant", entityId: variantId("SKU012"), entityLabel: "SKU012 — Crompton Ceiling Fan 1200mm", action: "updated", description: "Reorder point raised from 20 to 25", beforeData: { reorderPoint: 20 }, afterData: { reorderPoint: 25 }, changedFields: ["reorderPoint"], actorUserId: USER.owner, actorName: "Sharad", actorRole: "Owner", createdAt: "2026-09-06T10:12:00+05:30" },
  { id: "aud_10", entityType: "user", entityId: USER.staff, entityLabel: "Vikas Sharma", action: "invited", description: "Invited as Staff with access to Main Godown", actorUserId: USER.owner, actorName: "Sharad", actorRole: "Owner", createdAt: "2026-08-14T09:40:00+05:30" },
  { id: "aud_11", entityType: "supplier", entityId: SUPPLIER.indore, entityLabel: "Indore Home Needs", action: "deactivated", description: "Deactivated — repeated short supply", actorUserId: USER.owner, actorName: "Sharad", actorRole: "Owner", createdAt: "2026-06-20T17:05:00+05:30" },
  { id: "aud_12", entityType: "ai_extraction", entityId: "aix_" + QUOTE.ahmedabad, entityLabel: "aec_quotation_441.xlsx", action: "approved", description: "Promoted to quotation AEC-2026-441", actorUserId: USER.purchaseMgr, actorName: "Anita Deshpande", actorRole: "Purchase Manager", createdAt: "2026-09-09T12:40:00+05:30" },
];

/* -------------------------------------------------------------- Reports */

export const reportDefinitions: ReportDefinition[] = [
  { key: "stock_summary", name: "Stock Summary", description: "Closing balance and value by product and godown.", group: "Inventory", href: "/reports/stock-summary", params: ["godown", "category"] },
  { key: "stock_ledger", name: "Stock Ledger", description: "Every movement for a product, with running balance.", group: "Inventory", href: "/reports/stock-ledger", params: ["dateRange", "godown", "category"] },
  { key: "low_stock", name: "Low Stock & Reorder", description: "Items at or below reorder point with suggested order quantity.", group: "Inventory", href: "/reports/low-stock", params: ["godown", "category"] },
  { key: "inventory_valuation", name: "Inventory Valuation", description: "Stock value at purchase cost, by category and godown.", group: "Inventory", href: "/reports/valuation", params: ["godown", "category"] },
  { key: "batch_expiry", name: "Batch Expiry", description: "Batches in stock by expiry date.", group: "Inventory", href: "/reports/batch-expiry", params: ["dateRange", "godown"] },
  { key: "purchase_register", name: "Purchase Register", description: "Goods receipts and supplier invoices for a period.", group: "Procurement", href: "/reports/purchase-register", params: ["dateRange", "supplier"] },
  { key: "po_status", name: "PO Status", description: "Open, partially received and closed purchase orders.", group: "Procurement", href: "/reports/po-status", params: ["dateRange", "supplier", "status"] },
  { key: "pending_receipts", name: "Pending Receipts", description: "Ordered quantity still awaited, by PO line.", group: "Procurement", href: "/reports/pending-receipts", params: ["supplier", "godown"] },
  { key: "supplier_performance", name: "Supplier Performance", description: "On-time delivery, short supply and rejection rate.", group: "Procurement", href: "/reports/supplier-performance", params: ["dateRange", "supplier"] },
  { key: "price_variance", name: "Price Variance", description: "Invoice and proforma rates against PO rates.", group: "Procurement", href: "/reports/price-variance", params: ["dateRange", "supplier"] },
  { key: "gst_purchase", name: "GST Purchase Summary", description: "Taxable value and tax by GST rate for the period.", group: "Procurement", href: "/reports/gst-purchase", params: ["dateRange", "supplier"] },
  { key: "product_master", name: "Product Master", description: "Full catalogue with category, brand, HSN and rates.", group: "Master Data", href: "/reports/product-master", params: ["category"] },
  { key: "supplier_master", name: "Supplier Master", description: "Suppliers with GSTIN, terms and contact details.", group: "Master Data", href: "/reports/supplier-master", params: ["status"] },
];

/* ----------------------------------------------------- Outbound messages */

export const outboundMessages: OutboundMessage[] = [
  { id: "obm_1", channel: "email", messageType: "rfq", relatedType: "rfq", relatedId: RFQ.appliances, supplierId: SUPPLIER.reliance, toAddress: "b2b@reliance.example", subject: "RFQ-2026-00057 — Kitchen and Home Appliances", status: "delivered", sentAt: "2026-09-10T11:30:00+05:30" },
  { id: "obm_2", channel: "email", messageType: "rfq", relatedType: "rfq", relatedId: RFQ.appliances, supplierId: SUPPLIER.flipkart, toAddress: "wholesale@flipkart.example", subject: "RFQ-2026-00057 — Kitchen and Home Appliances", status: "delivered", sentAt: "2026-09-10T11:30:00+05:30" },
  { id: "obm_3", channel: "email", messageType: "rfq", relatedType: "rfq", relatedId: RFQ.appliances, supplierId: SUPPLIER.lg, toAddress: "channel@lg.example", subject: "RFQ-2026-00057 — Kitchen and Home Appliances", status: "delivered", sentAt: "2026-09-10T11:30:00+05:30" },
  { id: "obm_4", channel: "email", messageType: "purchase_order", relatedType: "purchase_order", relatedId: PO.reliance123, supplierId: SUPPLIER.reliance, toAddress: "b2b@reliance.example", subject: "Purchase Order PO-2026-00123", status: "delivered", sentAt: "2026-09-10T16:00:00+05:30" },
  { id: "obm_5", channel: "email", messageType: "proforma_query", relatedType: "proforma_invoice", relatedId: "pi_00041", supplierId: SUPPLIER.reliance, toAddress: "b2b@reliance.example", subject: "Query on proforma RR/PI/2026/0413", status: "sent", sentAt: "2026-09-11T18:20:00+05:30" },
  { id: "obm_6", channel: "email", messageType: "purchase_return", relatedType: "purchase_return", relatedId: PURCHASE_RETURN.ahmedabad, supplierId: SUPPLIER.ahmedabad, toAddress: "jignesh@amdelectricals.example", subject: "Debit Note DN-2026-00007 — 2 damaged fans", status: "delivered", sentAt: "2026-09-10T12:20:00+05:30" },
  { id: "obm_7", channel: "email", messageType: "invitation", supplierId: null, toAddress: "priya.nair@example.com", subject: "You have been invited to InventoryAI", status: "sent", sentAt: "2026-09-12T10:05:00+05:30" },
  { id: "obm_8", channel: "email", messageType: "rfq", relatedType: "rfq", relatedId: RFQ.electricals, supplierId: SUPPLIER.reliance, toAddress: "b2b@reliance.example", subject: "RFQ-2026-00056 — Electricals restock", status: "bounced", sentAt: "2026-09-08T11:30:00+05:30", errorMessage: "Mailbox full" },
];
