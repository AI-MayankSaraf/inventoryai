import {
  BarChart3,
  Boxes,
  Building2,
  ClipboardList,
  FileSearch,
  FileSpreadsheet,
  KeyRound,
  LayoutDashboard,
  Package,
  PackageCheck,
  ReceiptText,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Undo2,
  UserCog,
  Warehouse,
  type LucideIcon,
} from "lucide-react";

import type { PermissionCode } from "@/types";

/**
 * Navigation.
 *
 * Every entry declares the permission it needs, and the sidebar hides what the
 * signed-in role cannot use. Badge counts are no longer hardcoded — they are
 * supplied at render time from live data (I13), so a "3" next to Quotations
 * always matches the list behind it.
 */

export interface NavChild {
  label: string;
  href: string;
  permission: PermissionCode;
  /** Key into the live badge counts supplied by the sidebar. */
  badgeKey?: NavBadgeKey;
}

export interface NavItem {
  label: string;
  href?: string;
  icon: LucideIcon;
  permission: PermissionCode;
  badgeKey?: NavBadgeKey;
  children?: NavChild[];
}

export interface NavSection {
  title?: string;
  items: NavItem[];
}

export type NavBadgeKey =
  | "quotationsToReview"
  | "openPurchaseOrders"
  | "lowStock"
  | "documentsToReview"
  | "unreadAlerts"
  | "openVariances";

export type NavBadges = Partial<Record<NavBadgeKey, number>>;

export const NAV_SECTIONS: NavSection[] = [
  {
    items: [{ label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, permission: "dashboard.view" }],
  },
  {
    title: "Master Data",
    items: [
      { label: "Products", href: "/products", icon: Package, permission: "product.view" },
      { label: "Suppliers", href: "/suppliers", icon: Building2, permission: "supplier.view" },
      { label: "Godowns", href: "/godowns", icon: Warehouse, permission: "godown.view" },
    ],
  },
  {
    title: "Operations",
    items: [
      {
        label: "Procurement",
        icon: ShoppingCart,
        permission: "rfq.view",
        children: [
          { label: "RFQ", href: "/procurement/rfq", permission: "rfq.view" },
          {
            label: "Supplier Quotations",
            href: "/procurement/quotations",
            permission: "quotation.view",
            badgeKey: "quotationsToReview",
          },
          { label: "Quote Comparison", href: "/procurement/comparison", permission: "comparison.view" },
          { label: "Proforma", href: "/procurement/proforma", permission: "proforma.view" },
          {
            label: "Purchase Orders",
            href: "/procurement/purchase-orders",
            permission: "po.view",
            badgeKey: "openPurchaseOrders",
          },
        ],
      },
      { label: "Goods Receipt", href: "/goods-receipt", icon: PackageCheck, permission: "grn.view" },
      {
        label: "Payables",
        icon: ReceiptText,
        permission: "invoice.view",
        children: [
          {
            label: "Supplier Invoices",
            href: "/supplier-invoices",
            permission: "invoice.view",
            badgeKey: "openVariances",
          },
          { label: "Purchase Returns", href: "/purchase-returns", permission: "return.view" },
        ],
      },
      {
        label: "Inventory",
        icon: Boxes,
        permission: "inventory.view",
        children: [
          { label: "Current Stock", href: "/inventory/current-stock", permission: "inventory.view" },
          { label: "Stock by Godown", href: "/inventory/by-godown", permission: "inventory.view" },
          { label: "Transactions", href: "/inventory/transactions", permission: "inventory.view" },
          { label: "Stock Transfers", href: "/inventory/transfers", permission: "inventory.transfer" },
          {
            label: "Low Stock",
            href: "/inventory/low-stock",
            permission: "inventory.view",
            badgeKey: "lowStock",
          },
        ],
      },
    ],
  },
  {
    title: "Intelligence",
    items: [
      {
        label: "AI Documents",
        href: "/ai-documents",
        icon: FileSearch,
        permission: "ai.view",
        badgeKey: "documentsToReview",
      },
      {
        label: "Schema Mappings",
        href: "/schema-mappings",
        icon: FileSpreadsheet,
        permission: "ai.manage_mappings",
      },
      { label: "AI Assistant", href: "/assistant", icon: Sparkles, permission: "ai.assistant" },
      { label: "Reports", href: "/reports", icon: BarChart3, permission: "report.view" },
    ],
  },
  {
    title: "Administration",
    items: [
      { label: "Users", href: "/users", icon: UserCog, permission: "user.view" },
      { label: "Roles & Permissions", href: "/roles", icon: KeyRound, permission: "user.manage" },
      { label: "Audit Trail", href: "/audit", icon: ClipboardList, permission: "audit.view" },
      { label: "Settings", href: "/settings", icon: Settings, permission: "company.view" },
    ],
  },
  {
    title: "Platform",
    items: [
      {
        label: "System Admin",
        href: "/system-admin",
        icon: ShieldCheck,
        permission: "platform.companies.view",
      },
    ],
  },
];

/** Icons used by screens that are not themselves nav entries. */
export const EXTRA_ICONS = { Undo2 };
