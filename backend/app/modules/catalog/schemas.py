"""
Request/response models for the master-data endpoints.

Each resource has three: `*Create` (what you must supply), `*Update` (the
same fields, all optional — PATCH semantics, with `exclude_unset` in the
router so an omitted field is left alone rather than nulled), and `*Out`
(what comes back). They're written out rather than generated so the OpenAPI
docs — which is what the frontend will code against — show real field names
and constraints instead of a generic blob.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

# Patterns pinned to the schema's own CHECK constraints, so a bad value is
# refused at the edge with a readable message instead of becoming a 500
# from Postgres.
_TRACKING_TYPES = "^(none|batch|serial)$"
_GST_TREATMENTS = "^(regular|composition|unregistered|overseas)$"
_SUPPLIER_STATUS = "^(active|inactive)$"
_UOM_TYPES = "^(count|weight|volume|length)$"


# ------------------------------------------------------------- products

class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    base_uom_id: UUID
    brand_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    manufacturer_name: Optional[str] = None
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    gst_rate: float = Field(default=18.00, ge=0, le=28)
    cess_rate: float = Field(default=0.00, ge=0)
    tracking_type: str = Field(default="none", pattern=_TRACKING_TYPES)
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    base_uom_id: Optional[UUID] = None
    brand_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    manufacturer_name: Optional[str] = None
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    gst_rate: Optional[float] = Field(default=None, ge=0, le=28)
    cess_rate: Optional[float] = Field(default=None, ge=0)
    tracking_type: Optional[str] = Field(default=None, pattern=_TRACKING_TYPES)
    is_active: Optional[bool] = None


class ProductOut(BaseModel):
    id: UUID
    name: str
    brand_id: Optional[UUID]
    category_id: Optional[UUID]
    manufacturer_name: Optional[str]
    description: Optional[str]
    hsn_code: Optional[str]
    gst_rate: float
    cess_rate: float
    tracking_type: str
    base_uom_id: UUID
    is_active: bool


# ------------------------------------------------------------- variants

class VariantCreate(BaseModel):
    product_id: UUID
    sku: str = Field(min_length=1, max_length=100)
    uom_id: UUID
    variant_name: Optional[str] = None
    barcode: Optional[str] = None
    hsn_code: Optional[str] = None
    gst_rate: Optional[float] = Field(default=None, ge=0, le=28)
    pack_size: Optional[float] = Field(default=None, gt=0)
    purchase_price: float = Field(default=0, ge=0)
    sale_price: float = Field(default=0, ge=0)
    mrp: float = Field(default=0, ge=0)
    reorder_point: float = Field(default=0, ge=0)
    reorder_qty: float = Field(default=0, ge=0)
    lead_time_days: Optional[int] = Field(default=None, ge=0)
    is_active: bool = True


class VariantUpdate(BaseModel):
    sku: Optional[str] = Field(default=None, min_length=1, max_length=100)
    uom_id: Optional[UUID] = None
    variant_name: Optional[str] = None
    barcode: Optional[str] = None
    hsn_code: Optional[str] = None
    gst_rate: Optional[float] = Field(default=None, ge=0, le=28)
    pack_size: Optional[float] = Field(default=None, gt=0)
    purchase_price: Optional[float] = Field(default=None, ge=0)
    sale_price: Optional[float] = Field(default=None, ge=0)
    mrp: Optional[float] = Field(default=None, ge=0)
    reorder_point: Optional[float] = Field(default=None, ge=0)
    reorder_qty: Optional[float] = Field(default=None, ge=0)
    lead_time_days: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class VariantOut(BaseModel):
    id: UUID
    product_id: UUID
    sku: str
    variant_name: Optional[str]
    barcode: Optional[str]
    hsn_code: Optional[str]
    gst_rate: Optional[float]
    uom_id: UUID
    pack_size: Optional[float]
    purchase_price: float
    sale_price: float
    mrp: float
    reorder_point: float
    reorder_qty: float
    lead_time_days: Optional[int]
    attributes: dict
    is_active: bool


# ------------------------------------------------------------ suppliers

class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    supplier_type: str = Field(min_length=1, max_length=100)
    supplier_code: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    gst_treatment: str = Field(default="regular", pattern=_GST_TREATMENTS)
    city: Optional[str] = None
    state_code: Optional[str] = None
    state_name: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    primary_contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    payment_terms: Optional[str] = None
    payment_terms_days: Optional[int] = Field(default=None, ge=0)
    credit_limit: Optional[float] = Field(default=None, ge=0)
    status: str = Field(default="active", pattern=_SUPPLIER_STATUS)
    bank_name: Optional[str] = Field(default=None, max_length=200)
    bank_account_no: Optional[str] = Field(default=None, max_length=40)
    bank_ifsc: Optional[str] = Field(default=None, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    notes: Optional[str] = Field(default=None, max_length=4000)


class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    supplier_type: Optional[str] = None
    supplier_code: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    gst_treatment: Optional[str] = Field(default=None, pattern=_GST_TREATMENTS)
    city: Optional[str] = None
    state_code: Optional[str] = None
    state_name: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    primary_contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    payment_terms: Optional[str] = None
    payment_terms_days: Optional[int] = Field(default=None, ge=0)
    credit_limit: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = Field(default=None, pattern=_SUPPLIER_STATUS)
    bank_name: Optional[str] = Field(default=None, max_length=200)
    bank_account_no: Optional[str] = Field(default=None, max_length=40)
    bank_ifsc: Optional[str] = Field(default=None, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    notes: Optional[str] = Field(default=None, max_length=4000)


class SupplierOut(BaseModel):
    id: UUID
    name: str
    supplier_code: Optional[str]
    supplier_type: str
    gstin: Optional[str]
    pan: Optional[str]
    gst_treatment: str
    city: Optional[str]
    state_code: Optional[str]
    state_name: Optional[str]
    address: Optional[str]
    pincode: Optional[str]
    primary_contact_name: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    payment_terms: Optional[str]
    payment_terms_days: Optional[int]
    credit_limit: Optional[float]
    status: str
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_ifsc: Optional[str] = None
    notes: Optional[str] = None


# -------------------------------------------------------------- godowns

class GodownCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    code: Optional[str] = None
    city: Optional[str] = None
    state_code: Optional[str] = None
    address: Optional[str] = None
    gstin: Optional[str] = None
    is_active: bool = True
    #: The person responsible for this godown — a user of this company.
    incharge_user_id: Optional[UUID] = None
    #: Storage capacity, e.g. 5000 in Kg or 1200 in Box. Both or neither.
    capacity_value: Optional[float] = Field(default=None, gt=0)
    capacity_uom_id: Optional[UUID] = None


class GodownUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    code: Optional[str] = None
    city: Optional[str] = None
    state_code: Optional[str] = None
    address: Optional[str] = None
    gstin: Optional[str] = None
    is_active: Optional[bool] = None
    incharge_user_id: Optional[UUID] = None
    capacity_value: Optional[float] = Field(default=None, gt=0)
    capacity_uom_id: Optional[UUID] = None


class GodownOut(BaseModel):
    id: UUID
    name: str
    code: Optional[str]
    city: Optional[str]
    state_code: Optional[str]
    address: Optional[str]
    gstin: Optional[str]
    is_default: bool
    is_active: bool
    incharge_user_id: Optional[UUID] = None
    capacity_value: Optional[float] = None
    capacity_uom_id: Optional[UUID] = None


# ----------------------------------------------------------- categories

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    code: Optional[str] = None
    parent_id: Optional[UUID] = None
    is_active: bool = True


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    code: Optional[str] = None
    parent_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class CategoryOut(BaseModel):
    id: UUID
    name: str
    code: Optional[str]
    parent_id: Optional[UUID]
    is_active: bool


# --------------------------------------------------------------- brands

class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    code: Optional[str] = None
    manufacturer_name: Optional[str] = None
    is_active: bool = True


class BrandUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    code: Optional[str] = None
    manufacturer_name: Optional[str] = None
    is_active: Optional[bool] = None


class BrandOut(BaseModel):
    id: UUID
    name: str
    code: Optional[str]
    manufacturer_name: Optional[str]
    is_active: bool


# ----------------------------------------------------------------- UoMs

class UomCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    uom_type: str = Field(default="count", pattern=_UOM_TYPES)
    decimal_places: int = Field(default=0, ge=0, le=6)
    is_active: bool = True


class UomUpdate(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=20)
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    uom_type: Optional[str] = Field(default=None, pattern=_UOM_TYPES)
    decimal_places: Optional[int] = Field(default=None, ge=0, le=6)
    is_active: Optional[bool] = None


class UomOut(BaseModel):
    id: UUID
    code: str
    name: str
    uom_type: str
    decimal_places: int
    is_active: bool
