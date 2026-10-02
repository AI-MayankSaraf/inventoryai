"""
Request/response models for the supplier and catalogue *detail* panels —
everything behind the Supplier detail and Product detail screens that is
not the master row itself.

Numbers go out as `float` (the convention every other module uses); the
columns underneath are NUMERIC, so services convert explicitly rather than
letting a `Decimal` leak into the JSON as a string.
"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

_MATCH_SOURCES = "^(manual|ai_confirmed|imported)$"
# Deliberately a plain shape check, not `EmailStr`: that rejects reserved
# TLDs such as `.test`, which the dev/demo data uses throughout.
_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# ------------------------------------------------------------ contacts

class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    designation: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=254, pattern=_EMAIL)
    is_primary: bool = False


class ContactUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    designation: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=254, pattern=_EMAIL)
    is_primary: Optional[bool] = None


class ContactOut(BaseModel):
    id: UUID
    supplier_id: UUID
    name: str
    designation: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    is_primary: bool


# -------------------------------------------- supplier ⇄ SKU links

class SupplierProductUpsert(BaseModel):
    """One supplier's code/terms for one of our SKUs. Upserted on
    (supplier, variant) — confirming the same pair twice updates it."""

    product_variant_id: UUID
    supplier_sku: Optional[str] = Field(default=None, max_length=100)
    supplier_description: Optional[str] = Field(default=None, max_length=500)
    supplier_uom_id: Optional[UUID] = None
    conversion_to_base: float = Field(default=1, gt=0, le=1_000_000)
    lead_time_days: Optional[int] = Field(default=None, ge=0, le=365)
    is_preferred: bool = False
    match_source: str = Field(default="manual", pattern=_MATCH_SOURCES)


class SupplierProductOut(BaseModel):
    """`id` is null for a row derived purely from purchase history (the
    supplier has been bought from for this SKU, but nobody has recorded
    their item code yet) — `match_source` is then `purchase_history`."""

    id: Optional[UUID]
    supplier_id: UUID
    supplier_name: str
    product_variant_id: UUID
    sku: str
    product_name: str
    supplier_sku: Optional[str]
    supplier_description: Optional[str]
    supplier_uom_id: Optional[UUID]
    conversion_to_base: float
    last_quoted_price: Optional[float]
    last_quoted_at: Optional[date]
    last_purchase_price: Optional[float]
    last_purchase_at: Optional[date]
    lead_time_days: Optional[int]
    is_preferred: bool
    match_source: str
    confirmed_at: Optional[datetime]


# --------------------------------------------------------- performance

class SupplierPerformanceOut(BaseModel):
    supplier_id: UUID
    products_supplied: int
    total_purchases: float
    open_orders: int
    on_time_delivery_pct: int
    quality_score_pct: int
    open_variances: int


class SupplierOrderOut(BaseModel):
    id: UUID
    po_number: str
    po_date: date
    status: str
    total_amount: float
    received_pct: float


class PriceHistoryOut(BaseModel):
    po_id: UUID
    po_number: str
    po_date: date
    unit_price: float
    change_pct: float


class UsageOut(BaseModel):
    in_use: bool
    reason: Optional[str] = None


# ---------------------------------------------------- UoM conversions

class ConversionCreate(BaseModel):
    """`from_uom_id` → the variant's own base unit. The target is never
    sent: BR-INV-08 converts *to base*, so any other target is meaningless."""

    from_uom_id: UUID
    factor: float = Field(gt=0, le=1_000_000)
    is_purchase_default: bool = False


class ConversionOut(BaseModel):
    id: UUID
    product_variant_id: UUID
    from_uom_id: UUID
    from_code: str
    to_uom_id: UUID
    to_code: str
    factor: float
    is_purchase_default: bool


# ------------------------------------------- product images & documents

class ProductFileOut(BaseModel):
    id: UUID
    document_id: UUID
    product_variant_id: Optional[UUID]
    is_primary: bool
    is_image: bool
    original_filename: str
    mime_type: str
    file_extension: str
    file_size_bytes: int
    uploaded_at: datetime
    uploaded_by_name: str
    #: Signed, expires in minutes (BR-DOC-03) — re-list for a fresh one.
    url: str
    url_expires_at: datetime


# --------------------------------------------- per-godown reorder levels

class GodownPolicyIn(BaseModel):
    godown_id: UUID
    reorder_point: float = Field(default=0, ge=0, le=1_000_000_000)
    reorder_qty: float = Field(default=0, ge=0, le=1_000_000_000)
    max_stock: Optional[float] = Field(default=None, ge=0, le=1_000_000_000)
    is_stocked: bool = True

    @model_validator(mode="after")
    def _max_not_below_reorder(self):
        if self.max_stock is not None and self.max_stock < self.reorder_point:
            raise ValueError("max_stock cannot be below reorder_point")
        return self


class GodownPoliciesPut(BaseModel):
    """The complete set for one variant. A godown missing from the list
    falls back to the variant's own reorder point."""

    policies: list[GodownPolicyIn] = Field(default_factory=list, max_length=200)


class GodownPolicyOut(BaseModel):
    id: UUID
    product_variant_id: UUID
    godown_id: UUID
    godown_name: str
    reorder_point: float
    reorder_qty: float
    max_stock: Optional[float]
    is_stocked: bool
