/**
 * Stable, readable ids for the seeded dataset.
 *
 * The real backend issues UUIDs; readable ids here make the mock data legible
 * while behaving identically (opaque strings used only for relationships).
 * Anything created at runtime gets a generated id from `newId()`.
 */

let counter = 0;

export function newId(prefix: string): string {
  counter += 1;
  return `${prefix}_${Date.now().toString(36)}${counter.toString(36)}`;
}

export const COMPANY_ID = "co_acme";
export const PLATFORM_COMPANY_ID = "co_platform";

export const ROLE = {
  superAdmin: "role_super_admin",
  owner: "role_owner",
  purchase: "role_purchase_manager",
  godown: "role_godown_manager",
  accountant: "role_accountant",
  staff: "role_staff",
  viewer: "role_viewer",
} as const;

export const USER = {
  owner: "usr_sharad",
  platform: "usr_platform",
  godownMgr: "usr_mahesh",
  purchaseMgr: "usr_anita",
  accountant: "usr_rajesh",
  staff: "usr_vikas",
} as const;

export const GODOWN = {
  main: "gd_main",
  secondary: "gd_secondary",
} as const;

export const UOM = {
  nos: "uom_nos",
  pack: "uom_pack",
  pkt: "uom_pkt",
  box: "uom_box",
  bag: "uom_bag",
  set: "uom_set",
  kg: "uom_kg",
  litre: "uom_litre",
  metre: "uom_metre",
} as const;

export const CATEGORY = {
  homeAppliances: "cat_home_appliances",
  cookware: "cat_cookware",
  largeAppliances: "cat_large_appliances",
  fmcg: "cat_fmcg",
  grocery: "cat_grocery",
  hardware: "cat_hardware",
  electricals: "cat_electricals",
} as const;

export const BRAND = {
  pigeon: "brd_pigeon",
  philips: "brd_philips",
  lg: "brd_lg",
  aashirvaad: "brd_aashirvaad",
  haldiram: "brd_haldiram",
  crompton: "brd_crompton",
  havells: "brd_havells",
  whirlpool: "brd_whirlpool",
  prestige: "brd_prestige",
  bajaj: "brd_bajaj",
  generic: "brd_generic",
} as const;

export const SUPPLIER = {
  reliance: "sup_reliance",
  flipkart: "sup_flipkart",
  lg: "sup_lg",
  sundram: "sup_sundram",
  ahmedabad: "sup_ahmedabad",
  balaji: "sup_balaji",
  whirlpool: "sup_whirlpool",
  indore: "sup_indore_home",
  malwa: "sup_malwa",
} as const;

/**
 * Seeded document ids. Screens deep-link by id (`/purchase-orders/po_123`),
 * so these stay stable and the document *number* is display-only (C12).
 */
export const RFQ = {
  appliances: "rfq_00057",
  electricals: "rfq_00056",
  fasteners: "rfq_00055",
  fmcg: "rfq_00054",
  festive: "rfq_00058",
} as const;

export const QUOTE = {
  reliance: "qtn_rr_3391",
  flipkart: "qtn_fk_8821",
  lg: "qtn_lg_556102",
  ahmedabad: "qtn_aec_441",
  sundram: "qtn_sfl_2291",
} as const;

export const COMPARISON = {
  appliances: "cmp_00057",
} as const;

export const PO = {
  reliance123: "po_00123",
  lg122: "po_00122",
  whirlpool121: "po_00121",
  sundram120: "po_00120",
  ahmedabad119: "po_00119",
  flipkart124: "po_00124",
  malwa125: "po_00125",
} as const;

export const PROFORMA = {
  reliance: "pi_00041",
  lg: "pi_00040",
  sundram: "pi_00039",
} as const;

export const GRN = {
  lg88: "grn_00088",
  reliance91: "grn_00091",
  sundram90: "grn_00090",
  ahmedabad89: "grn_00089",
} as const;

export const SUPPLIER_INVOICE = {
  sundram: "sinv_sfl_4471",
  ahmedabad: "sinv_aec_2210",
  lg: "sinv_lg_90233",
} as const;

export const PURCHASE_RETURN = {
  ahmedabad: "pret_00007",
} as const;

/** variant id ⇄ SKU. The SKU stays the human-facing code. */
export const variantId = (sku: string) => `var_${sku.toLowerCase()}`;
export const productId = (sku: string) => `prd_${sku.toLowerCase()}`;
