"""
Master data — `02_DATABASE_DESIGN.md` §4.

categories, brands, uoms, godowns, suppliers are tenant-scoped reference
tables. products -> product_variants is the split described at length in
§4 ("why split product/variant when the UI is flat") — variants, not
products, are what inventory/procurement ever reference.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    AuditMixin,
    Base,
    Factor,
    Money,
    Pct,
    Qty,
    Rate,
    SoftDeleteMixin,
    TenantMixin,
    UUIDPkMixin,
    enum_check,
    plain_fk,
    self_tenant_fk,
    tenant_fk,
    uq_company_id,
)


class Category(UUIDPkMixin, TenantMixin, Base):
    """Self-referencing to model the UI's `category` + `subcategory`."""

    __tablename__ = "categories"

    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(Text)
    path: Mapped[Optional[str]] = mapped_column(Text, index=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(index=True)

    __table_args__ = (
        uq_company_id("categories"),
        self_tenant_fk("categories", "parent_id", ondelete="RESTRICT"),
        Index(
            "uq_categories_name",
            "company_id",
            "parent_id",
            func.lower(name),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class Brand(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "brands"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(Text)
    manufacturer_name: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(index=True)

    __table_args__ = (
        uq_company_id("brands"),
        Index(
            "uq_brands_name",
            "company_id",
            func.lower(name),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class Uom(UUIDPkMixin, Base):
    """`company_id IS NULL` = system UoM available to all tenants. Not
    `TenantMixin` — company_id here must be nullable. Seed: Nos, Pack, Pkt,
    Box, Bag, Set, Kg, Litre, Metre."""

    __tablename__ = "uoms"

    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    uom_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'count'"))
    decimal_places: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    __table_args__ = (enum_check("uom_type", ["count", "weight", "volume", "length"]),)


class Product(UUIDPkMixin, TenantMixin, Base):
    """The catalogue item — the thing a buyer talks about. Stock never
    attaches here; see `ProductVariant`."""

    __tablename__ = "products"

    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    slug: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    brand_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    manufacturer_name: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    hsn_code: Mapped[Optional[str]] = mapped_column(Text, index=True)
    gst_rate: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("18.00"))
    cess_rate: Mapped[float] = mapped_column(Pct, nullable=False, server_default=text("0.00"))
    tracking_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    base_uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    display_emoji: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"), index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(index=True)

    __table_args__ = (
        uq_company_id("products"),
        tenant_fk("products", "brand_id", "brands", ondelete="RESTRICT"),
        tenant_fk("products", "category_id", "categories", ondelete="RESTRICT"),
        enum_check("tracking_type", ["none", "batch", "serial"]),
        CheckConstraint("gst_rate BETWEEN 0 AND 28", name="gst_rate_range"),
    )


class ProductVariant(UUIDPkMixin, TenantMixin, Base):
    """The stockable, orderable, priced unit. **This is the SKU.** Everything
    in inventory and procurement references `product_variant_id`, never
    `product_id`. `currentStock`/`reserved`/`status`/`godowns[]` are
    deliberately NOT columns here — see `stock_balances` in inventory.py."""

    __tablename__ = "product_variants"

    product_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(Text, nullable=False)
    variant_name: Mapped[Optional[str]] = mapped_column(Text)
    barcode: Mapped[Optional[str]] = mapped_column(Text, index=True)
    ean: Mapped[Optional[str]] = mapped_column(Text, index=True)
    upc: Mapped[Optional[str]] = mapped_column(Text, index=True)
    mpn: Mapped[Optional[str]] = mapped_column(Text, index=True)
    model_code: Mapped[Optional[str]] = mapped_column(Text, index=True)
    hsn_code: Mapped[Optional[str]] = mapped_column(Text, index=True)
    gst_rate: Mapped[Optional[float]] = mapped_column(Pct)
    uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    pack_size: Mapped[Optional[float]] = mapped_column(Qty)
    purchase_price: Mapped[float] = mapped_column(Rate, nullable=False, server_default=text("0"))
    sale_price: Mapped[float] = mapped_column(Rate, nullable=False, server_default=text("0"))
    mrp: Mapped[float] = mapped_column(Rate, nullable=False, server_default=text("0"))
    reorder_point: Mapped[float] = mapped_column(Qty, nullable=False, server_default=text("0"), index=True)
    reorder_qty: Mapped[float] = mapped_column(Qty, nullable=False, server_default=text("0"))
    lead_time_days: Mapped[Optional[int]] = mapped_column(SmallInteger)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    search_text: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"), index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(index=True)

    __table_args__ = (
        uq_company_id("product_variants"),
        tenant_fk("product_variants", "product_id", "products", ondelete="RESTRICT"),
        # Trigram search for the match ladder's text-similarity rung
        # (migration e42a7c1b95d0).
        Index(
            "ix_product_variants_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        Index(
            "uq_variant_sku",
            "company_id",
            func.upper(sku),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_variant_barcode",
            "company_id",
            "barcode",
            unique=True,
            postgresql_where=text("barcode IS NOT NULL AND deleted_at IS NULL"),
        ),
        CheckConstraint("gst_rate IS NULL OR gst_rate BETWEEN 0 AND 28", name="gst_rate_range"),
    )


class ProductUomConversion(UUIDPkMixin, TenantMixin, Base):
    """(RECOMMENDED) Needed the first time a supplier quotes "1 Box = 12
    Nos"."""

    __tablename__ = "product_uom_conversions"

    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    from_uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    to_uom_id: Mapped[uuid.UUID] = plain_fk("uoms.id", nullable=False)
    factor: Mapped[float] = mapped_column(Factor, nullable=False)
    is_purchase_default: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    __table_args__ = (
        uq_company_id("product_uom_conversions"),
        tenant_fk("product_uom_conversions", "product_variant_id", "product_variants", ondelete="CASCADE"),
        UniqueConstraint("product_variant_id", "from_uom_id", "to_uom_id", name="uq_conversion"),
        CheckConstraint("factor > 0", name="factor_positive"),
    )


class ProductImage(UUIDPkMixin, TenantMixin, Base):
    """(RECOMMENDED) Backs the empty "Images & Documents" panel."""

    __tablename__ = "product_images"

    product_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    product_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    document_id: Mapped[uuid.UUID] = plain_fk("documents.id", nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    __table_args__ = (
        uq_company_id("product_images"),
        tenant_fk("product_images", "product_id", "products", ondelete="CASCADE"),
        tenant_fk("product_images", "product_variant_id", "product_variants", ondelete="CASCADE"),
    )


class Godown(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "godowns"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(Text)
    state_code: Mapped[Optional[str]] = mapped_column(Text)
    address: Mapped[Optional[str]] = mapped_column(Text)
    gstin: Mapped[Optional[str]] = mapped_column(Text)
    incharge_user_id: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    capacity_value: Mapped[Optional[float]] = mapped_column(Qty)
    capacity_uom_id: Mapped[Optional[uuid.UUID]] = plain_fk("uoms.id")
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"), index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(index=True)

    __table_args__ = (
        uq_company_id("godowns"),
        UniqueConstraint("company_id", "name", name="uq_godowns_name"),
        UniqueConstraint("company_id", "code", name="uq_godowns_code"),
    )


class Supplier(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_code: Mapped[Optional[str]] = mapped_column(Text)
    gstin: Mapped[Optional[str]] = mapped_column(Text)
    pan: Mapped[Optional[str]] = mapped_column(Text)
    gst_treatment: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'regular'"))
    supplier_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    city: Mapped[Optional[str]] = mapped_column(Text, index=True)
    state_code: Mapped[Optional[str]] = mapped_column(Text, index=True)
    state_name: Mapped[Optional[str]] = mapped_column(Text)
    address: Mapped[Optional[str]] = mapped_column(Text)
    pincode: Mapped[Optional[str]] = mapped_column(Text)
    primary_contact_name: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text, index=True)
    payment_terms: Mapped[Optional[str]] = mapped_column(Text)
    payment_terms_days: Mapped[Optional[int]] = mapped_column(SmallInteger)
    credit_limit: Mapped[Optional[float]] = mapped_column(Money)
    bank_name: Mapped[Optional[str]] = mapped_column(Text)
    bank_account_no: Mapped[Optional[str]] = mapped_column(Text)
    bank_ifsc: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"), index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(index=True)

    __table_args__ = (
        uq_company_id("suppliers"),
        Index(
            "uq_supplier_name",
            "company_id",
            func.lower(name),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_supplier_gstin",
            "company_id",
            "gstin",
            unique=True,
            postgresql_where=text("gstin IS NOT NULL AND deleted_at IS NULL"),
        ),
        enum_check("gst_treatment", ["regular", "composition", "unregistered", "overseas"]),
        enum_check("status", ["active", "inactive"]),
    )


class SupplierContact(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "supplier_contacts"

    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    designation: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    __table_args__ = (
        uq_company_id("supplier_contacts"),
        tenant_fk("supplier_contacts", "supplier_id", "suppliers", ondelete="CASCADE"),
        Index(
            "uq_supplier_contact_email",
            "supplier_id",
            func.lower(email),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
    )


class SupplierProduct(UUIDPkMixin, TenantMixin, Base):
    """The supplier's own code and price for one of our SKUs — what makes AI
    matching converge over time (§4)."""

    __tablename__ = "supplier_products"

    supplier_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    supplier_sku: Mapped[Optional[str]] = mapped_column(Text, index=True)
    supplier_description: Mapped[Optional[str]] = mapped_column(Text, index=True)
    supplier_uom_id: Mapped[Optional[uuid.UUID]] = plain_fk("uoms.id")
    conversion_to_base: Mapped[float] = mapped_column(Factor, nullable=False, server_default=text("1"))
    last_quoted_price: Mapped[Optional[float]] = mapped_column(Rate)
    last_quoted_at: Mapped[Optional[date]] = mapped_column(Date)
    last_purchase_price: Mapped[Optional[float]] = mapped_column(Rate)
    last_purchase_at: Mapped[Optional[date]] = mapped_column(Date)
    lead_time_days: Mapped[Optional[int]] = mapped_column(SmallInteger)
    is_preferred: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"), index=True)
    match_source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    confirmed_by: Mapped[Optional[uuid.UUID]] = plain_fk("users.id", ondelete="SET NULL")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column()

    __table_args__ = (
        uq_company_id("supplier_products"),
        tenant_fk("supplier_products", "supplier_id", "suppliers", ondelete="CASCADE"),
        Index(
            "ix_supplier_products_desc_trgm",
            "supplier_description",
            postgresql_using="gin",
            postgresql_ops={"supplier_description": "gin_trgm_ops"},
        ),
        tenant_fk("supplier_products", "product_variant_id", "product_variants", ondelete="RESTRICT"),
        Index(
            "uq_supplier_sku",
            "company_id",
            "supplier_id",
            func.upper(supplier_sku),
            unique=True,
            postgresql_where=text("supplier_sku IS NOT NULL"),
        ),
        enum_check("match_source", ["manual", "ai_confirmed", "imported"]),
    )
