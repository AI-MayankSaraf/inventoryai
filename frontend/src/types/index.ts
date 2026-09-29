/**
 * Domain model barrel.
 *
 * Mirrors `02_DATABASE_DESIGN.md`. Key rules baked into these types:
 *
 *  - Product and ProductVariant (the SKU) are separate; stock attaches to the
 *    variant and only ever as a sum of inventory transactions.
 *  - Every cross-document relationship is an id. Document numbers are display
 *    values only.
 *  - Godowns, suppliers, categories, brands and UoMs are referenced by id,
 *    never by name.
 *  - Financial totals live on the document and are produced by one service.
 */

export * from "./common";
export * from "./master";
export * from "./inventory";
export * from "./procurement";
export * from "./documents";
export * from "./ops";
