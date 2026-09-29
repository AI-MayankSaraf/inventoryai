"use client";

import * as React from "react";
import { Lock } from "lucide-react";

import { AsyncBoundary, FormError, LoadingCard } from "@/components/common/async-state";
import { ChangePasswordCard } from "@/components/admin/change-password-card";
import { CompanyListsCard } from "@/components/admin/company-lists-card";
import { EmailSettingsCard } from "@/components/admin/email-settings-card";
import { EmbeddingIndexCard } from "@/components/admin/embedding-index-card";
import { PageHeader } from "@/components/common/page-header";
import { PermissionButton } from "@/components/common/permission-gate";
import { SectionCard } from "@/components/common/section-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ConfirmButton } from "@/components/common/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  useCloseInventoryPeriod,
  useCompanySettings,
  useDocumentSequences,
  useGodownsWithUsage,
  useUpdateCompanyProfile,
  useUpdateCompanySettings,
} from "@/hooks/use-admin";
import { usePermission } from "@/hooks/use-session";
import { formatDate } from "@/lib/format";
import { INDIAN_STATES } from "@/lib/gst-states";
import type { Company, CompanySettings, DocSequenceType } from "@/types";

/**
 * Real values other screens read: numbering, the period lock and approval
 * thresholds all live in `CompanySettings` and are written here through the
 * same API every other mutation goes through — nothing on this screen is a
 * constant baked into a component (I14, I15).
 */

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DOC_TYPE_LABELS: Record<DocSequenceType, string> = {
  rfq: "RFQ",
  po: "Purchase Order",
  grn: "Goods Receipt",
  proforma: "Proforma Invoice",
  invoice: "Supplier Invoice",
  transfer: "Stock Transfer",
  return: "Purchase Return",
  adjustment: "Stock Adjustment",
};

interface ProfileForm {
  name: string;
  gstin: string;
  pan: string;
  stateCode: string;
  city: string;
  pincode: string;
  addressLine1: string;
  addressLine2: string;
}

function toProfileForm(company: Company): ProfileForm {
  return {
    name: company.name ?? "",
    gstin: company.gstin ?? "",
    pan: company.pan ?? "",
    stateCode: company.stateCode ?? "",
    city: company.city ?? "",
    pincode: company.pincode ?? "",
    addressLine1: company.addressLine1 ?? "",
    addressLine2: company.addressLine2 ?? "",
  };
}

interface SettingsForm {
  currencyCode: string;
  defaultGstRate: string;
  roundingMode: CompanySettings["roundingMode"];
  financialYearStartMonth: string;
  defaultGodownId: string;
  allowNegativeStock: boolean;
  allowGrnExcessReceipt: boolean;
  grnExcessTolerancePct: string;
  requirePoApprovalAbove: string;
  requireMakerChecker: boolean;
  variancePriceTolerancePct: string;
  varianceAmountTolerance: string;
  aiAutoProcess: boolean;
  aiReviewConfidenceThreshold: string;
  aiSuggestWhileTyping: boolean;
}

function toSettingsForm(settings: CompanySettings): SettingsForm {
  return {
    currencyCode: settings.currencyCode,
    defaultGstRate: String(settings.defaultGstRate),
    roundingMode: settings.roundingMode,
    financialYearStartMonth: String(settings.financialYearStartMonth),
    defaultGodownId: settings.defaultGodownId ?? "",
    allowNegativeStock: settings.allowNegativeStock,
    allowGrnExcessReceipt: settings.allowGrnExcessReceipt,
    grnExcessTolerancePct: String(settings.grnExcessTolerancePct),
    requirePoApprovalAbove: settings.requirePoApprovalAbove == null ? "" : String(settings.requirePoApprovalAbove),
    requireMakerChecker: settings.requireMakerChecker,
    variancePriceTolerancePct: String(settings.variancePriceTolerancePct),
    varianceAmountTolerance: String(settings.varianceAmountTolerance),
    aiAutoProcess: settings.aiAutoProcess,
    aiReviewConfidenceThreshold: String(settings.aiReviewConfidenceThreshold),
    aiSuggestWhileTyping: settings.aiSuggestWhileTyping,
  };
}

export function SettingsScreen() {
  const settingsState = useCompanySettings();
  const sequencesState = useDocumentSequences();
  const godownsState = useGodownsWithUsage();
  const canManage = usePermission("company.manage");

  const saveProfile = useUpdateCompanyProfile();
  const saveSettings = useUpdateCompanySettings();
  const closePeriod = useCloseInventoryPeriod();

  const [profileForm, setProfileForm] = React.useState<ProfileForm | null>(null);
  const [form, setForm] = React.useState<SettingsForm | null>(null);
  const [closeDate, setCloseDate] = React.useState("");
  const initialized = React.useRef(false);

  React.useEffect(() => {
    if (!initialized.current && settingsState.data) {
      setProfileForm(toProfileForm(settingsState.data.company));
      setForm(toSettingsForm(settingsState.data.settings));
      initialized.current = true;
    }
  }, [settingsState.data]);

  function setField<K extends keyof SettingsForm>(key: K, value: SettingsForm[K]) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  function setProfileField<K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) {
    setProfileForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" description="How InventoryAI behaves for your business" />

      <AsyncBoundary state={settingsState} loading={<LoadingCard />}>
        {({ settings }) => {
          if (!profileForm || !form) return <LoadingCard />;

          return (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
              <div className="space-y-4 lg:col-span-7">
                <SectionCard
                  title="Company Profile"
                  action={
                    <PermissionButton
                      permission="company.manage"
                      size="sm"
                      disabled={saveProfile.isPending}
                      onClick={() => saveProfile.run({
                        name: profileForm.name,
                        gstin: profileForm.gstin || null,
                        pan: profileForm.pan || null,
                        stateCode: profileForm.stateCode,
                        stateName: INDIAN_STATES.find((s) => s.code === profileForm.stateCode)?.name ?? "",
                        city: profileForm.city,
                        pincode: profileForm.pincode || undefined,
                        addressLine1: profileForm.addressLine1,
                        addressLine2: profileForm.addressLine2 || undefined,
                      })}
                    >
                      {saveProfile.isPending ? "Saving..." : "Save Profile"}
                    </PermissionButton>
                  }
                >
                  <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="s-name">Business Name</Label>
                      <Input id="s-name" value={profileForm.name} onChange={(e) => setProfileField("name", e.target.value)} disabled={!canManage} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-gstin">GSTIN</Label>
                      <Input id="s-gstin" value={profileForm.gstin} onChange={(e) => setProfileField("gstin", e.target.value.toUpperCase())} className="font-mono" disabled={!canManage} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-pan">PAN</Label>
                      <Input id="s-pan" value={profileForm.pan} onChange={(e) => setProfileField("pan", e.target.value.toUpperCase())} className="font-mono" disabled={!canManage} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-state">State</Label>
                      <Select value={profileForm.stateCode} onValueChange={(v) => setProfileField("stateCode", v)} disabled={!canManage}>
                        <SelectTrigger id="s-state"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {INDIAN_STATES.map((s) => (
                            <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-city">City</Label>
                      <Input id="s-city" value={profileForm.city} onChange={(e) => setProfileField("city", e.target.value)} disabled={!canManage} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-pincode">Pincode</Label>
                      <Input id="s-pincode" value={profileForm.pincode} onChange={(e) => setProfileField("pincode", e.target.value)} disabled={!canManage} />
                    </div>
                    <div className="space-y-1.5 sm:col-span-2">
                      <Label htmlFor="s-addr1">Address Line 1</Label>
                      <Input id="s-addr1" value={profileForm.addressLine1} onChange={(e) => setProfileField("addressLine1", e.target.value)} disabled={!canManage} />
                    </div>
                    <div className="space-y-1.5 sm:col-span-2">
                      <Label htmlFor="s-addr2">Address Line 2</Label>
                      <Input id="s-addr2" value={profileForm.addressLine2} onChange={(e) => setProfileField("addressLine2", e.target.value)} disabled={!canManage} />
                    </div>
                  </div>
                  {(saveProfile.error) && (
                    <div className="px-4 pb-4">
                      <FormError message={saveProfile.error} fieldErrors={saveProfile.fieldErrors} />
                    </div>
                  )}
                  {settingsState.data && (
                    <p className="border-t px-4 py-3 text-caption text-muted-foreground">
                      {settingsState.data.company.plan} plan
                      {settingsState.data.company.ownerEmail && <> · Owner {settingsState.data.company.ownerEmail}</>}
                      {" "}· Customer since {formatDate(settingsState.data.company.onboardedOn)}
                    </p>
                  )}
                </SectionCard>

                <SectionCard title="Financial" description="Currency, tax and the working financial year">
                  <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="s-currency">Currency</Label>
                      <Select value={form.currencyCode} onValueChange={(v) => setField("currencyCode", v)} disabled={!canManage}>
                        <SelectTrigger id="s-currency"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="INR">₹ Indian Rupee (INR)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-gst">Default GST Rate</Label>
                      <Select value={form.defaultGstRate} onValueChange={(v) => setField("defaultGstRate", v)} disabled={!canManage}>
                        <SelectTrigger id="s-gst"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {["0", "5", "12", "18", "28"].map((rate) => (
                            <SelectItem key={rate} value={rate}>{rate}%</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-round">Rounding</Label>
                      <Select value={form.roundingMode} onValueChange={(v) => setField("roundingMode", v as CompanySettings["roundingMode"])} disabled={!canManage}>
                        <SelectTrigger id="s-round"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="nearest">Nearest rupee</SelectItem>
                          <SelectItem value="up">Always round up</SelectItem>
                          <SelectItem value="none">No rounding</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-fy">Financial Year Starts</Label>
                      <Select value={form.financialYearStartMonth} onValueChange={(v) => setField("financialYearStartMonth", v)} disabled={!canManage}>
                        <SelectTrigger id="s-fy"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {MONTHS.map((m, i) => (
                            <SelectItem key={m} value={String(i + 1)}>{m}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5 sm:col-span-2">
                      <Label htmlFor="s-godown">Default Godown</Label>
                      <Select value={form.defaultGodownId || "none"} onValueChange={(v) => setField("defaultGodownId", v === "none" ? "" : v)} disabled={!canManage}>
                        <SelectTrigger id="s-godown"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">Not set</SelectItem>
                          {(godownsState.data ?? []).map((g) => (
                            <SelectItem key={g.id} value={g.id}>{g.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </SectionCard>

                <SectionCard title="Inventory Policy">
                  <div className="space-y-4 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[13.5px] font-medium text-foreground">Allow negative stock</p>
                        <p className="text-caption text-muted-foreground">
                          Let a transaction post even if it would take a balance below zero.
                        </p>
                      </div>
                      <Switch checked={form.allowNegativeStock} onCheckedChange={(v) => setField("allowNegativeStock", v)} disabled={!canManage} />
                    </div>

                    <div className="border-t border-border pt-4">
                      <Label htmlFor="s-close-through">Close period through</Label>
                      <p className="mt-0.5 mb-2 text-caption text-muted-foreground">
                        Nothing can be posted on or before the closing date once it is set — this cannot be undone from here.
                      </p>
                      {settings.inventoryLockedThrough && (
                        <p className="mb-2 text-[12.5px] text-foreground">
                          Currently closed through <span className="font-medium">{formatDate(settings.inventoryLockedThrough)}</span>.
                        </p>
                      )}
                      <div className="flex flex-wrap items-center gap-2">
                        <Input
                          id="s-close-through"
                          type="date"
                          className="max-w-[180px]"
                          value={closeDate}
                          onChange={(e) => setCloseDate(e.target.value)}
                          disabled={!canManage}
                        />
                        <ConfirmButton
                          variant="outline"
                          tone="warning"
                          title="Close the inventory period?"
                          description={`Nothing can be posted on or before ${closeDate || "the closing date"} once this is confirmed.`}
                          confirmLabel="Close Period"
                          disabled={!canManage || !closeDate}
                          onConfirm={async () => {
                            await closePeriod.run(closeDate);
                          }}
                        >
                          Close Period
                        </ConfirmButton>
                      </div>
                      <FormError message={closePeriod.error} className="mt-2" />
                    </div>
                  </div>
                </SectionCard>

                <SectionCard title="Receiving">
                  <div className="space-y-4 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[13.5px] font-medium text-foreground">Allow excess receipt</p>
                        <p className="text-caption text-muted-foreground">
                          Let a GRN receive more than ordered, within the tolerance below.
                        </p>
                      </div>
                      <Switch checked={form.allowGrnExcessReceipt} onCheckedChange={(v) => setField("allowGrnExcessReceipt", v)} disabled={!canManage} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-excess-pct">Excess tolerance (%)</Label>
                      <Input
                        id="s-excess-pct"
                        type="number"
                        min={0}
                        max={50}
                        value={form.grnExcessTolerancePct}
                        onChange={(e) => setField("grnExcessTolerancePct", e.target.value)}
                        disabled={!canManage || !form.allowGrnExcessReceipt}
                        className="max-w-[140px]"
                      />
                    </div>
                  </div>
                </SectionCard>

                <SectionCard title="Approvals">
                  <div className="space-y-4 p-4">
                    <div className="space-y-1.5">
                      <Label htmlFor="s-po-threshold">Require approval for POs above (₹)</Label>
                      <Input
                        id="s-po-threshold"
                        type="number"
                        min={0}
                        placeholder="No threshold"
                        value={form.requirePoApprovalAbove}
                        onChange={(e) => setField("requirePoApprovalAbove", e.target.value)}
                        disabled={!canManage}
                        className="max-w-[200px]"
                      />
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[13.5px] font-medium text-foreground">Require maker-checker</p>
                        <p className="text-caption text-muted-foreground">
                          The person who approves a document cannot be the one who created it.
                        </p>
                      </div>
                      <Switch checked={form.requireMakerChecker} onCheckedChange={(v) => setField("requireMakerChecker", v)} disabled={!canManage} />
                    </div>
                  </div>
                </SectionCard>

                <SectionCard title="Variance Tolerance" description="How far a GRN/invoice can drift before it is flagged">
                  <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="s-var-pct">Price variance tolerance (%)</Label>
                      <Input id="s-var-pct" type="number" min={0} value={form.variancePriceTolerancePct} onChange={(e) => setField("variancePriceTolerancePct", e.target.value)} disabled={!canManage} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="s-var-amt">Amount variance tolerance (₹)</Label>
                      <Input id="s-var-amt" type="number" min={0} value={form.varianceAmountTolerance} onChange={(e) => setField("varianceAmountTolerance", e.target.value)} disabled={!canManage} />
                    </div>
                  </div>
                </SectionCard>
              </div>

              <div className="space-y-4 lg:col-span-5">
                <SectionCard title="AI Behaviour" description="AI assists — it never decides on its own">
                  <ul className="divide-y divide-border">
                    <li className="flex items-start gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-[13.5px] font-medium text-foreground">Auto-process uploaded documents</p>
                        <p className="text-caption text-muted-foreground">Start extraction as soon as a file is uploaded.</p>
                      </div>
                      <Switch checked={form.aiAutoProcess} onCheckedChange={(v) => setField("aiAutoProcess", v)} disabled={!canManage} />
                    </li>
                    <li className="flex items-start gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-[13.5px] font-medium text-foreground">Review confidence threshold (%)</p>
                        <p className="text-caption text-muted-foreground">Extractions below this confidence need a person before approval.</p>
                        <Input
                          type="number"
                          min={0}
                          max={100}
                          className="mt-2 max-w-[120px]"
                          value={form.aiReviewConfidenceThreshold}
                          onChange={(e) => setField("aiReviewConfidenceThreshold", e.target.value)}
                          disabled={!canManage}
                        />
                      </div>
                    </li>
                    <li className="flex items-start gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-[13.5px] font-medium text-foreground">Suggest matches while typing</p>
                        <p className="text-caption text-muted-foreground">Normalise free-text descriptions against your catalogue.</p>
                      </div>
                      <Switch checked={form.aiSuggestWhileTyping} onCheckedChange={(v) => setField("aiSuggestWhileTyping", v)} disabled={!canManage} />
                    </li>
                    <li className="flex items-start gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-[13.5px] font-medium text-foreground">Never auto-approve financial values</p>
                        <p className="text-caption text-muted-foreground">Prices, taxes and totals always need a person&apos;s approval.</p>
                        <p className="mt-1 text-[11.5px] font-medium text-ai-subtle-foreground">
                          Locked on — the server refuses to turn this off.
                        </p>
                      </div>
                      <Switch checked disabled />
                    </li>
                  </ul>
                </SectionCard>

                <CompanyListsCard />

                <EmbeddingIndexCard />

                <EmailSettingsCard />

                <ChangePasswordCard />

                <SectionCard
                  title="Document Numbering"
                  description="Issued by the server when a document is saved — gaps are normal"
                >
                  <ul className="divide-y divide-border">
                    {(sequencesState.data ?? []).map((seq) => (
                      <li key={seq.id} className="flex items-center justify-between gap-3 px-4 py-3">
                        <div className="min-w-0">
                          <p className="text-[13.5px] font-medium text-foreground">{DOC_TYPE_LABELS[seq.docType]}</p>
                          <p className="text-caption text-muted-foreground">FY {seq.financialYear}</p>
                        </div>
                        <div className="text-right">
                          <p className="font-mono text-[13px] text-foreground">
                            {seq.prefix}{String(seq.nextNumber).padStart(seq.padding, "0")}
                          </p>
                          <p className="text-caption text-muted-foreground">next number</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                </SectionCard>

                {!canManage && (
                  <Alert variant="default">
                    <Lock />
                    <AlertDescription>
                      You don&apos;t have permission to change company settings. Fields are shown for reference only.
                    </AlertDescription>
                  </Alert>
                )}

                <div className="flex items-center justify-end gap-2">
                  <PermissionButton
                    permission="company.manage"
                    disabled={saveSettings.isPending}
                    onClick={() => saveSettings.run({
                      currencyCode: form.currencyCode,
                      defaultGstRate: Number(form.defaultGstRate),
                      roundingMode: form.roundingMode,
                      financialYearStartMonth: Number(form.financialYearStartMonth),
                      defaultGodownId: form.defaultGodownId || null,
                      allowNegativeStock: form.allowNegativeStock,
                      allowGrnExcessReceipt: form.allowGrnExcessReceipt,
                      grnExcessTolerancePct: Number(form.grnExcessTolerancePct),
                      requirePoApprovalAbove: form.requirePoApprovalAbove === "" ? null : Number(form.requirePoApprovalAbove),
                      requireMakerChecker: form.requireMakerChecker,
                      variancePriceTolerancePct: Number(form.variancePriceTolerancePct),
                      varianceAmountTolerance: Number(form.varianceAmountTolerance),
                      aiAutoProcess: form.aiAutoProcess,
                      aiReviewConfidenceThreshold: Number(form.aiReviewConfidenceThreshold),
                      aiSuggestWhileTyping: form.aiSuggestWhileTyping,
                    })}
                  >
                    {saveSettings.isPending ? "Saving..." : "Save Settings"}
                  </PermissionButton>
                </div>
                <FormError message={saveSettings.error} fieldErrors={saveSettings.fieldErrors} />
              </div>
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
