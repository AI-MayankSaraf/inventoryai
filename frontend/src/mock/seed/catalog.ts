import type {
  Brand,
  Category,
  Godown,
  Product,
  ProductUomConversion,
  ProductVariant,
  StockPolicy,
  TrackingType,
  Uom,
} from "@/types";
import { BRAND, CATEGORY, GODOWN, UOM, productId, USER, variantId } from "../ids";

const T = { createdAt: "2025-02-01T10:00:00+05:30", updatedAt: "2026-09-01T10:00:00+05:30" };
const live = { isActive: true, deletedAt: null };

export const uoms: Uom[] = [
  { id: UOM.nos, code: "NOS", name: "Nos", uomType: "count", decimalPlaces: 0, isActive: true },
  { id: UOM.pack, code: "PACK", name: "Pack", uomType: "count", decimalPlaces: 0, isActive: true },
  { id: UOM.pkt, code: "PKT", name: "Pkt", uomType: "count", decimalPlaces: 0, isActive: true },
  { id: UOM.box, code: "BOX", name: "Box", uomType: "count", decimalPlaces: 0, isActive: true },
  { id: UOM.bag, code: "BAG", name: "Bag", uomType: "count", decimalPlaces: 0, isActive: true },
  { id: UOM.set, code: "SET", name: "Set", uomType: "count", decimalPlaces: 0, isActive: true },
  { id: UOM.kg, code: "KG", name: "Kg", uomType: "weight", decimalPlaces: 3, isActive: true },
  { id: UOM.litre, code: "LTR", name: "Litre", uomType: "volume", decimalPlaces: 3, isActive: true },
  { id: UOM.metre, code: "MTR", name: "Metre", uomType: "length", decimalPlaces: 2, isActive: true },
];

export const categories: Category[] = [
  { id: CATEGORY.homeAppliances, parentId: null, name: "Home Appliances", path: "Home Appliances", ...live },
  { id: CATEGORY.cookware, parentId: CATEGORY.homeAppliances, name: "Cookware", path: "Home Appliances/Cookware", ...live },
  { id: CATEGORY.largeAppliances, parentId: null, name: "Large Appliances", path: "Large Appliances", ...live },
  { id: CATEGORY.fmcg, parentId: null, name: "FMCG", path: "FMCG", ...live },
  { id: CATEGORY.grocery, parentId: null, name: "Grocery", path: "Grocery", ...live },
  { id: CATEGORY.hardware, parentId: null, name: "Hardware", path: "Hardware", ...live },
  { id: CATEGORY.electricals, parentId: null, name: "Electricals", path: "Electricals", ...live },
];

export const brands: Brand[] = [
  { id: BRAND.pigeon, name: "Pigeon", manufacturerName: "Stovekraft Ltd", ...live },
  { id: BRAND.philips, name: "Philips", manufacturerName: "Signify Innovations India Ltd", ...live },
  { id: BRAND.lg, name: "LG", manufacturerName: "LG Electronics India Pvt Ltd", ...live },
  { id: BRAND.aashirvaad, name: "Aashirvaad", manufacturerName: "ITC Ltd", ...live },
  { id: BRAND.haldiram, name: "Haldiram", manufacturerName: "Haldiram Foods International", ...live },
  { id: BRAND.crompton, name: "Crompton", manufacturerName: "Crompton Greaves Consumer Electricals", ...live },
  { id: BRAND.havells, name: "Havells", manufacturerName: "Havells India Ltd", ...live },
  { id: BRAND.whirlpool, name: "Whirlpool", manufacturerName: "Whirlpool of India Ltd", ...live },
  { id: BRAND.prestige, name: "Prestige", manufacturerName: "TTK Prestige Ltd", ...live },
  { id: BRAND.bajaj, name: "Bajaj", manufacturerName: "Bajaj Electricals Ltd", ...live },
  { id: BRAND.generic, name: "Generic", ...live },
];

export const godowns: Godown[] = [
  {
    id: GODOWN.main, name: "Main Godown", code: "MAIN", city: "Indore", stateCode: "23",
    address: "Plot 14, Scheme 78, Vijay Nagar, Indore 452010",
    gstin: "23AACCA1234F1Z5", inchargeUserId: USER.owner, inchargeName: "Sharad",
    capacityValue: 10000, capacityUomId: UOM.nos, isDefault: true, ...live, ...T,
  },
  {
    id: GODOWN.secondary, name: "Secondary Godown", code: "SEC", city: "Pune", stateCode: "27",
    address: "Unit 6, Bhosari MIDC, Pune 411026",
    gstin: null, inchargeUserId: USER.godownMgr, inchargeName: "Mahesh Pawar",
    capacityValue: 6000, capacityUomId: UOM.nos, isDefault: false, ...live, ...T,
  },
];

/** sku, name, brand, category, hsn, gst, purchase, sale, mrp, reorderPoint, reorderQty, uom, tracking, emoji, attributes */
type SeedRow = {
  sku: string;
  name: string;
  brandId: string;
  categoryId: string;
  hsn: string;
  gst: number;
  purchase: number;
  sale: number;
  mrp: number;
  reorderPoint: number;
  reorderQty: number;
  uomId: string;
  tracking?: TrackingType;
  emoji: string;
  mpn?: string;
  barcode?: string;
  modelCode?: string;
  attributes: Record<string, string>;
};

const ROWS: SeedRow[] = [
  {
    sku: "SKU001", name: "Pigeon Cooker 5L", brandId: BRAND.pigeon, categoryId: CATEGORY.cookware,
    hsn: "7615", gst: 18, purchase: 1180, sale: 1490, mrp: 1795, reorderPoint: 20, reorderQty: 50,
    uomId: UOM.nos, emoji: "🍲", mpn: "PGN-PC-5L", barcode: "8901234500011", modelCode: "Favourite 5L",
    attributes: { Capacity: "5 Litre", Material: "Aluminium", Colour: "Silver", "Pack Size": "1 Nos" },
  },
  {
    sku: "SKU002", name: "Philips Mixer Grinder 750W", brandId: BRAND.philips, categoryId: CATEGORY.homeAppliances,
    hsn: "8509", gst: 18, purchase: 2800, sale: 3450, mrp: 3995, reorderPoint: 15, reorderQty: 40,
    uomId: UOM.nos, emoji: "🥤", mpn: "HL7756", barcode: "8901234500028", modelCode: "HL7756/00",
    attributes: { Power: "750 W", Jars: "3", Colour: "White", Warranty: "2 years" },
  },
  {
    sku: "SKU003", name: "LG Refrigerator 260L", brandId: BRAND.lg, categoryId: CATEGORY.largeAppliances,
    hsn: "8418", gst: 28, purchase: 24000, sale: 27500, mrp: 31990, reorderPoint: 10, reorderQty: 15,
    uomId: UOM.nos, emoji: "🧊", mpn: "GL-S292RPZY", barcode: "8901234500035", modelCode: "GL-S292RPZY",
    attributes: { Capacity: "260 Litre", Type: "Double Door", Colour: "Shiny Steel", Warranty: "1 yr + 10 yr compressor" },
  },
  {
    sku: "SKU004", name: "Aashirvaad Atta 10kg", brandId: BRAND.aashirvaad, categoryId: CATEGORY.grocery,
    hsn: "1101", gst: 5, purchase: 420, sale: 470, mrp: 495, reorderPoint: 40, reorderQty: 120,
    uomId: UOM.bag, tracking: "batch", emoji: "🌾", barcode: "8901234500042",
    attributes: { Weight: "10 kg", Type: "Whole Wheat", "Pack Size": "1 Bag" },
  },
  {
    sku: "SKU005", name: "Haldiram Namkeen 200g", brandId: BRAND.haldiram, categoryId: CATEGORY.fmcg,
    hsn: "2106", gst: 12, purchase: 42, sale: 52, mrp: 60, reorderPoint: 60, reorderQty: 300,
    uomId: UOM.pack, tracking: "batch", emoji: "🥟", barcode: "8901234500059",
    attributes: { Weight: "200 g", Variant: "Aloo Bhujia", "Pack Size": "1 Pack" },
  },
  {
    sku: "SKU010", name: "Prestige Induction Cooktop 1900W", brandId: BRAND.prestige, categoryId: CATEGORY.homeAppliances,
    hsn: "8516", gst: 18, purchase: 2150, sale: 2690, mrp: 3145, reorderPoint: 12, reorderQty: 30,
    uomId: UOM.nos, emoji: "🔥", mpn: "PIC-16.0", modelCode: "PIC 16.0",
    attributes: { Power: "1900 W", Colour: "Black", Warranty: "1 year" },
  },
  {
    sku: "SKU011", name: "Havells Ceiling Fan 1200mm", brandId: BRAND.havells, categoryId: CATEGORY.electricals,
    hsn: "8414", gst: 18, purchase: 1620, sale: 1990, mrp: 2350, reorderPoint: 20, reorderQty: 60,
    uomId: UOM.nos, emoji: "🌀", modelCode: "Velocity 1200",
    attributes: { Sweep: "1200 mm", Colour: "Brown", Warranty: "2 years" },
  },
  {
    sku: "SKU012", name: "Crompton Ceiling Fan 1200mm", brandId: BRAND.crompton, categoryId: CATEGORY.electricals,
    hsn: "8414", gst: 18, purchase: 1320, sale: 1650, mrp: 1899, reorderPoint: 25, reorderQty: 60,
    uomId: UOM.nos, emoji: "🌀", modelCode: "HS Plus 1200",
    attributes: { Sweep: "1200 mm", Colour: "Ivory", Warranty: "2 years" },
  },
  {
    sku: "SKU013", name: "Anchor Modular Switch", brandId: BRAND.generic, categoryId: CATEGORY.electricals,
    hsn: "8536", gst: 18, purchase: 95, sale: 125, mrp: 145, reorderPoint: 100, reorderQty: 500,
    uomId: UOM.nos, emoji: "🔌",
    attributes: { Type: "6A One-Way", Colour: "White", "Pack Size": "1 Nos" },
  },
  {
    sku: "SKU020", name: "Hex Bolt M8x40", brandId: BRAND.generic, categoryId: CATEGORY.hardware,
    hsn: "7318", gst: 18, purchase: 2.4, sale: 3.6, mrp: 4, reorderPoint: 2000, reorderQty: 5000,
    uomId: UOM.nos, emoji: "🔩", modelCode: "M8x40",
    attributes: { Thread: "M8", Length: "40 mm", Material: "Mild Steel", Head: "Hex" },
  },
  {
    sku: "SKU028", name: "SS Hex Bolt M10 × 50mm", brandId: BRAND.generic, categoryId: CATEGORY.hardware,
    hsn: "7318", gst: 18, purchase: 12, sale: 17, mrp: 20, reorderPoint: 1000, reorderQty: 3000,
    uomId: UOM.nos, emoji: "🔩", modelCode: "M10x50",
    attributes: { Thread: "M10", Length: "50 mm", Material: "Stainless Steel", Head: "Hex" },
  },
  {
    sku: "SKU031", name: "Havells LED Bulb 9W", brandId: BRAND.havells, categoryId: CATEGORY.electricals,
    hsn: "8539", gst: 12, purchase: 78, sale: 99, mrp: 120, reorderPoint: 150, reorderQty: 500,
    uomId: UOM.nos, emoji: "💡", modelCode: "Adore 9W",
    attributes: { Power: "9 W", Colour: "Cool Daylight", Base: "B22", "Pack Size": "1 Nos" },
  },
  {
    sku: "SKU035", name: "Whirlpool Washing Machine 7kg", brandId: BRAND.whirlpool, categoryId: CATEGORY.largeAppliances,
    hsn: "8450", gst: 28, purchase: 15800, sale: 18500, mrp: 21990, reorderPoint: 6, reorderQty: 12,
    uomId: UOM.nos, emoji: "🌊", modelCode: "WhiteMagic 7kg",
    attributes: { Capacity: "7 kg", Type: "Top Load", Warranty: "2 years" },
  },
  {
    sku: "SKU041", name: "Bajaj Water Heater 15L", brandId: BRAND.bajaj, categoryId: CATEGORY.homeAppliances,
    hsn: "8516", gst: 18, purchase: 4250, sale: 5200, mrp: 6100, reorderPoint: 12, reorderQty: 30,
    uomId: UOM.nos, emoji: "♨️", modelCode: "New Shakti 15L",
    attributes: { Capacity: "15 Litre", Type: "Storage", Warranty: "2 years" },
  },
];

export const products: Product[] = ROWS.map((r) => ({
  id: productId(r.sku),
  name: r.name,
  slug: r.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""),
  brandId: r.brandId,
  categoryId: r.categoryId,
  manufacturerName: brands.find((b) => b.id === r.brandId)?.manufacturerName,
  hsnCode: r.hsn,
  gstRate: r.gst,
  cessRate: 0,
  trackingType: r.tracking ?? "none",
  baseUomId: r.uomId,
  displayEmoji: r.emoji,
  ...live,
  ...T,
}));

export const productVariants: ProductVariant[] = ROWS.map((r) => ({
  id: variantId(r.sku),
  productId: productId(r.sku),
  sku: r.sku,
  barcode: r.barcode,
  ean: r.barcode,
  mpn: r.mpn,
  modelCode: r.modelCode,
  hsnCode: r.hsn,
  gstRate: r.gst,
  uomId: r.uomId,
  packSize: 1,
  purchasePrice: r.purchase,
  salePrice: r.sale,
  mrp: r.mrp,
  reorderPoint: r.reorderPoint,
  reorderQty: r.reorderQty,
  leadTimeDays: 7,
  attributes: r.attributes,
  searchText: [r.name, r.sku, r.modelCode, ...Object.values(r.attributes)]
    .filter(Boolean)
    .join(" ")
    .toLowerCase(),
  ...live,
  ...T,
}));

/** A few purchase-unit conversions so the UoM concept is demonstrable (I10). */
export const productUomConversions: ProductUomConversion[] = [
  { id: "conv_1", productVariantId: variantId("SKU013"), fromUomId: UOM.box, toUomId: UOM.nos, factor: 20, isPurchaseDefault: true },
  { id: "conv_2", productVariantId: variantId("SKU031"), fromUomId: UOM.box, toUomId: UOM.nos, factor: 10, isPurchaseDefault: true },
  { id: "conv_3", productVariantId: variantId("SKU020"), fromUomId: UOM.box, toUomId: UOM.nos, factor: 100, isPurchaseDefault: true },
  { id: "conv_4", productVariantId: variantId("SKU028"), fromUomId: UOM.box, toUomId: UOM.nos, factor: 50, isPurchaseDefault: true },
  { id: "conv_5", productVariantId: variantId("SKU005"), fromUomId: UOM.box, toUomId: UOM.pack, factor: 24, isPurchaseDefault: true },
];

/** Per-godown reorder overrides — only where they differ from the variant. */
export const stockPolicies: StockPolicy[] = [
  { id: "pol_1", productVariantId: variantId("SKU001"), godownId: GODOWN.secondary, reorderPoint: 10, reorderQty: 25, isStocked: true },
  { id: "pol_2", productVariantId: variantId("SKU005"), godownId: GODOWN.secondary, reorderPoint: 60, reorderQty: 300, isStocked: true },
];
