"use client";

/**
 * Add / edit a supplier.
 *
 * The new required shape: a state (code + name, which decides CGST/SGST vs
 * IGST on every document raised against this supplier), a GST treatment, and
 * payment-terms/bank detail. Validation messages all come from the API's
 * `fieldErrors` — this file does not duplicate the GSTIN or state-code rules.
 */

import * as React from "react";
import { Pencil, Plus } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { PermissionButton } from "@/components/common/permission-gate";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateSupplier, useUpdateSupplier } from "@/hooks/use-suppliers";
import type { suppliersApi } from "@/lib/api";
import type { GstTreatment, Supplier, SupplierStatus, SupplierType } from "@/types";

/** GST state-code table (`01`–`38`, plus the two special jurisdictions). */
const INDIAN_STATES: { code: string; name: string }[] = [
  { code: "01", name: "Jammu and Kashmir" },
  { code: "02", name: "Himachal Pradesh" },
  { code: "03", name: "Punjab" },
  { code: "04", name: "Chandigarh" },
  { code: "05", name: "Uttarakhand" },
  { code: "06", name: "Haryana" },
  { code: "07", name: "Delhi" },
  { code: "08", name: "Rajasthan" },
  { code: "09", name: "Uttar Pradesh" },
  { code: "10", name: "Bihar" },
  { code: "11", name: "Sikkim" },
  { code: "12", name: "Arunachal Pradesh" },
  { code: "13", name: "Nagaland" },
  { code: "14", name: "Manipur" },
  { code: "15", name: "Mizoram" },
  { code: "16", name: "Tripura" },
  { code: "17", name: "Meghalaya" },
  { code: "18", name: "Assam" },
  { code: "19", name: "West Bengal" },
  { code: "20", name: "Jharkhand" },
  { code: "21", name: "Odisha" },
  { code: "22", name: "Chhattisgarh" },
  { code: "23", name: "Madhya Pradesh" },
  { code: "24", name: "Gujarat" },
  { code: "25", name: "Daman and Diu" },
  { code: "26", name: "Dadra and Nagar Haveli" },
  { code: "27", name: "Maharashtra" },
  { code: "28", name: "Andhra Pradesh (Old)" },
  { code: "29", name: "Karnataka" },
  { code: "30", name: "Goa" },
  { code: "31", name: "Lakshadweep" },
  { code: "32", name: "Kerala" },
  { code: "33", name: "Tamil Nadu" },
  { code: "34", name: "Puducherry" },
  { code: "35", name: "Andaman and Nicobar Islands" },
  { code: "36", name: "Telangana" },
  { code: "37", name: "Andhra Pradesh" },
  { code: "38", name: "Ladakh" },
  { code: "97", name: "Other Territory" },
  { code: "99", name: "Centre Jurisdiction" },
];

const SUPPLIER_TYPES: SupplierType[] = ["Manufacturer", "Distributor", "Online", "Local Supplier", "Importer"];

const GST_TREATMENTS: { value: GstTreatment; label: string }[] = [
  { value: "regular", label: "Regular" },
  { value: "composition", label: "Composition" },
  { value: "unregistered", label: "Unregistered" },
  { value: "overseas", label: "Overseas" },
];

const STATUSES: { value: SupplierStatus; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
];

type FormState = {
  name: string;
  gstin: string;
  pan: string;
  gstTreatment: GstTreatment;
  supplierType: SupplierType;
  city: string;
  stateCode: string;
  address: string;
  pincode: string;
  primaryContactName: string;
  phone: string;
  email: string;
  paymentTerms: string;
  paymentTermsDays: string;
  bankName: string;
  bankAccountNo: string;
  bankIfsc: string;
  status: SupplierStatus;
};

function toFormState(s?: Supplier): FormState {
  return {
    name: s?.name ?? "",
    gstin: s?.gstin ?? "",
    pan: s?.pan ?? "",
    gstTreatment: s?.gstTreatment ?? "regular",
    supplierType: s?.supplierType ?? "Distributor",
    city: s?.city ?? "",
    stateCode: s?.stateCode ?? "",
    address: s?.address ?? "",
    pincode: s?.pincode ?? "",
    primaryContactName: s?.primaryContactName ?? "",
    phone: s?.phone ?? "",
    email: s?.email ?? "",
    paymentTerms: s?.paymentTerms ?? "30 Days",
    paymentTermsDays: String(s?.paymentTermsDays ?? 30),
    bankName: s?.bankName ?? "",
    bankAccountNo: s?.bankAccountNo ?? "",
    bankIfsc: s?.bankIfsc ?? "",
    status: s?.status ?? "active",
  };
}

export function SupplierFormDialog({
  supplier,
  onSaved,
  trigger,
}: {
  supplier?: Supplier;
  onSaved?: (supplier: Supplier) => void;
  trigger?: React.ReactNode;
}) {
  const isEdit = !!supplier;
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(() => toFormState(supplier));

  const create = useCreateSupplier((s) => {
    onSaved?.(s);
    setOpen(false);
  });
  const update = useUpdateSupplier(supplier?.id ?? "", (s) => {
    onSaved?.(s);
    setOpen(false);
  });
  const mutation = isEdit ? update : create;

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    mutation.reset();
    if (next) setForm(toFormState(supplier));
  }

  async function save() {
    const state = INDIAN_STATES.find((s) => s.code === form.stateCode);
    const input: suppliersApi.SupplierInput = {
      name: form.name.trim(),
      gstin: form.gstin.trim() || null,
      pan: form.pan.trim() || null,
      gstTreatment: form.gstTreatment,
      supplierType: form.supplierType,
      city: form.city.trim(),
      stateCode: form.stateCode,
      stateName: state?.name ?? supplier?.stateName ?? "",
      address: form.address.trim(),
      pincode: form.pincode.trim() || undefined,
      primaryContactName: form.primaryContactName.trim(),
      phone: form.phone.trim(),
      email: form.email.trim(),
      paymentTerms: form.paymentTerms.trim() || "30 Days",
      paymentTermsDays: form.paymentTermsDays ? Number(form.paymentTermsDays) : undefined,
      bankName: form.bankName.trim() || undefined,
      bankAccountNo: form.bankAccountNo.trim() || undefined,
      bankIfsc: form.bankIfsc.trim() || undefined,
      status: form.status,
      notes: supplier?.notes,
    };
    await mutation.run(input);
  }

  const canSubmit = !!form.name.trim() && !!form.stateCode && !mutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button>
            {isEdit ? <Pencil /> : <Plus />}
            {isEdit ? "Edit" : "Add Supplier"}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit supplier" : "Add a supplier"}</DialogTitle>
          <DialogDescription>
            {isEdit ? "Update this supplier's details." : "Add a new supplier to your directory."}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          <FormError message={mutation.error} fieldErrors={mutation.fieldErrors} />

          <div className="space-y-1.5">
            <Label htmlFor="sf-name">Supplier Name</Label>
            <Input id="sf-name" value={form.name} onChange={(e) => set("name", e.target.value)} autoFocus />
            {mutation.fieldErrors.name && (
              <p className="text-[12px] text-destructive">{mutation.fieldErrors.name}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-gstin">GSTIN</Label>
              <Input
                id="sf-gstin"
                value={form.gstin}
                onChange={(e) => set("gstin", e.target.value.toUpperCase())}
                className="font-mono"
              />
              {mutation.fieldErrors.gstin && (
                <p className="text-[12px] text-destructive">{mutation.fieldErrors.gstin}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-pan">PAN</Label>
              <Input
                id="sf-pan"
                value={form.pan}
                onChange={(e) => set("pan", e.target.value.toUpperCase())}
                className="font-mono"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-gst-treatment">GST Treatment</Label>
              <Select value={form.gstTreatment} onValueChange={(v) => set("gstTreatment", v as GstTreatment)}>
                <SelectTrigger id="sf-gst-treatment">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {GST_TREATMENTS.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-type">Supplier Type</Label>
              <Select value={form.supplierType} onValueChange={(v) => set("supplierType", v as SupplierType)}>
                <SelectTrigger id="sf-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SUPPLIER_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-city">City</Label>
              <Input id="sf-city" value={form.city} onChange={(e) => set("city", e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-state">State</Label>
              <Select value={form.stateCode} onValueChange={(v) => set("stateCode", v)}>
                <SelectTrigger id="sf-state">
                  <SelectValue placeholder="Choose a state" />
                </SelectTrigger>
                <SelectContent>
                  {INDIAN_STATES.map((s) => (
                    <SelectItem key={s.code} value={s.code}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {mutation.fieldErrors.stateCode && (
                <p className="text-[12px] text-destructive">{mutation.fieldErrors.stateCode}</p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5 col-span-2">
              <Label htmlFor="sf-address">Address</Label>
              <Input id="sf-address" value={form.address} onChange={(e) => set("address", e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-pincode">Pincode</Label>
              <Input id="sf-pincode" value={form.pincode} onChange={(e) => set("pincode", e.target.value)} className="font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-status">Status</Label>
              <Select value={form.status} onValueChange={(v) => set("status", v as SupplierStatus)}>
                <SelectTrigger id="sf-status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUSES.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-contact">Contact Person</Label>
              <Input
                id="sf-contact"
                value={form.primaryContactName}
                onChange={(e) => set("primaryContactName", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-phone">Phone</Label>
              <Input id="sf-phone" value={form.phone} onChange={(e) => set("phone", e.target.value)} />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="sf-email">Email</Label>
            <Input id="sf-email" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />
            {mutation.fieldErrors.email && (
              <p className="text-[12px] text-destructive">{mutation.fieldErrors.email}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-payment-terms">Payment Terms</Label>
              <Input
                id="sf-payment-terms"
                value={form.paymentTerms}
                onChange={(e) => set("paymentTerms", e.target.value)}
                placeholder="e.g. 30 Days"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-payment-terms-days">Payment Terms (days)</Label>
              <Input
                id="sf-payment-terms-days"
                type="number"
                min={0}
                value={form.paymentTermsDays}
                onChange={(e) => set("paymentTermsDays", e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-2.5 rounded-lg border border-border bg-muted/40 p-3.5">
            <p className="text-[13px] font-medium text-foreground">Bank details (optional)</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5 col-span-2">
                <Label htmlFor="sf-bank-name">Bank Name</Label>
                <Input id="sf-bank-name" value={form.bankName} onChange={(e) => set("bankName", e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sf-bank-account">Account Number</Label>
                <Input
                  id="sf-bank-account"
                  value={form.bankAccountNo}
                  onChange={(e) => set("bankAccountNo", e.target.value)}
                  className="font-mono"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sf-bank-ifsc">IFSC</Label>
                <Input
                  id="sf-bank-ifsc"
                  value={form.bankIfsc}
                  onChange={(e) => set("bankIfsc", e.target.value.toUpperCase())}
                  className="font-mono"
                />
              </div>
            </div>
          </div>
        </DialogBody>

        <DialogFooter>
          <PermissionButton
            permission={isEdit ? "supplier.update" : "supplier.create"}
            onClick={save}
            disabled={!canSubmit}
          >
            {mutation.isPending ? "Saving..." : isEdit ? "Save Changes" : "Add Supplier"}
          </PermissionButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
