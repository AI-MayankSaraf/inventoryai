"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  FileUp,
  History,
  Loader2,
  RefreshCw,
  Sparkles,
  Upload,
  Wand2,
} from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import { useUoms } from "@/hooks/use-catalog";
import { useImportRfq, useRfqImportPreview } from "@/hooks/use-procurement";
import type { procurementApi } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";

type Field = procurementApi.RfqImportField;
type Preview = procurementApi.RfqImportPreview;
type ColumnMap = Partial<Record<Field, number>>;

const STEPS = ["Upload", "Map columns", "Review & import"] as const;
const NONE = "__none__";
const MAX_BYTES = 10 * 1024 * 1024;

/** One colour per field, so a column in the file preview and the field it
 *  feeds read as the same thing. Token-based, so both themes work. */
const FIELD_TONE: Record<Field, string> = {
  description: "bg-primary-subtle text-primary-subtle-foreground ring-primary/30",
  quantity: "bg-success-subtle text-success-subtle-foreground ring-success/30",
  uom: "bg-warning-subtle text-warning-subtle-foreground ring-warning/40",
  price: "bg-info-subtle text-info-subtle-foreground ring-info/30",
  item_code: "bg-ai-subtle text-ai-subtle-foreground ring-ai-border/60",
  make: "bg-neutral-subtle text-neutral-subtle-foreground ring-border",
  hsn: "bg-neutral-subtle text-neutral-subtle-foreground ring-border",
  remarks: "bg-neutral-subtle text-neutral-subtle-foreground ring-border",
};

const FIELD_DOT: Record<Field, string> = {
  description: "bg-primary",
  quantity: "bg-success",
  uom: "bg-warning",
  price: "bg-info",
  item_code: "bg-ai-border",
  make: "bg-muted-foreground/60",
  hsn: "bg-muted-foreground/60",
  remarks: "bg-muted-foreground/60",
};

const FIELD_HINT: Record<Field, string> = {
  description: "Item name or specification",
  quantity: "\"10\" or \"10 Nos\" both work",
  uom: "Nos, Kg, Mtr, Pcs… — optional if the quantity carries it",
  price: "Target or last purchase rate",
  item_code: "Kept in the line's remarks",
  make: "Preferred make — kept in remarks",
  hsn: "Kept in remarks",
  remarks: "Any notes for the supplier",
};

function columnLetter(index: number): string {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const r = (n - 1) % 26;
    out = String.fromCharCode(65 + r) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const SAMPLE_CSV = [
  "Sr. No.,Item Description,Quantity,Unit,Expected Rate,Make,Remarks",
  "1,MCB 32A Double Pole,25,Nos,450,Havells,",
  "2,PVC Conduit Pipe 25mm,150,Mtr,38,,ISI marked",
  "3,Copper Wire 2.5 sqmm,5,Kg,650,Polycab,",
].join("\n");

function downloadSample() {
  const blob = new Blob([SAMPLE_CSV], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "rfq-import-sample.csv";
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Import an RFQ from whatever spreadsheet the buyer sent.
 *
 * There is no standard RFQ layout in India, so the file is read in three
 * layers (see `backend/app/modules/procurement/rfq_import.py`): a layout
 * imported before is recognised and reused; otherwise the header row and
 * columns are detected; and step 2 lets the person correct any of it. Every
 * change re-runs the server-side preview, so what step 3 shows is exactly
 * what Confirm Import will create — and importing saves the mapping.
 */
export function ImportRfqButton() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [step, setStep] = React.useState(0);
  const [file, setFile] = React.useState<File | null>(null);
  const [fileError, setFileError] = React.useState<string | null>(null);
  const [dragging, setDragging] = React.useState(false);

  // Overrides; `null` means "let the server decide".
  const [columnMap, setColumnMap] = React.useState<ColumnMap | null>(null);
  const [headerRow, setHeaderRow] = React.useState<number | null>(null);
  const [sheetIndex, setSheetIndex] = React.useState<number | null>(null);
  const [defaultUomId, setDefaultUomId] = React.useState<string | null>(null);

  const [sourceName, setSourceName] = React.useState("");
  const [referenceNumber, setReferenceNumber] = React.useState("");
  const [subject, setSubject] = React.useState("");

  const inputRef = React.useRef<HTMLInputElement>(null);
  const preview = useRfqImportPreview();
  const uoms = useUoms();
  const doImport = useImportRfq((rfq) => {
    setOpen(false);
    router.push(`/procurement/rfq/${rfq.id}`);
  });

  const options = React.useMemo(
    () => ({ columnMap, headerRow, sheetIndex, defaultUomId }),
    [columnMap, headerRow, sheetIndex, defaultUomId],
  );

  // Re-run the preview whenever the file or an override changes.
  const { run: runPreview } = preview;
  React.useEffect(() => {
    if (!file) return;
    const t = window.setTimeout(() => void runPreview(file, options), 150);
    return () => window.clearTimeout(t);
  }, [file, options, runPreview]);

  const resetAll = () => {
    setStep(0);
    setFile(null);
    setFileError(null);
    setColumnMap(null);
    setHeaderRow(null);
    setSheetIndex(null);
    setDefaultUomId(null);
    setSourceName("");
    setReferenceNumber("");
    setSubject("");
    preview.reset();
    doImport.reset();
  };

  const acceptFile = (f: File | undefined | null) => {
    if (!f) return;
    const name = f.name.toLowerCase();
    if (!/\.(xlsx|xlsm|xls|csv)$/.test(name)) {
      setFileError("Choose an Excel (.xlsx, .xls) or .csv file.");
      return;
    }
    if (f.size > MAX_BYTES) {
      setFileError("That file is over 10 MB.");
      return;
    }
    setFileError(null);
    setColumnMap(null);
    setHeaderRow(null);
    setSheetIndex(null);
    doImport.reset();
    setFile(f);
    setStep(1);
  };

  const data = preview.data;
  const blocking = !data || data.errors.length > 0 || data.rows.length === 0;
  const mappingReady = !!data && data.missingRequired.length === 0;

  const runImport = () => {
    if (!file || !data) return;
    void doImport.run({
      file,
      data: {
        externalSourceName: sourceName,
        externalReferenceNumber: referenceNumber || undefined,
        subject: subject || undefined,
        // Import exactly what was previewed: the mapping on screen, not a
        // fresh detection (which could ask the AI again and differ).
        columnMap: data.columnMap,
        headerRow: data.headerRow,
        sheetIndex: data.sheetIndex,
        defaultUomId,
      },
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) resetAll();
      }}
    >
      <Button variant="outline" onClick={() => setOpen(true)} data-testid="import-rfq">
        <FileUp />
        Import RFQ
      </Button>
      <DialogContent className="sm:max-w-5xl" data-testid="import-rfq-dialog">
        <DialogHeader>
          <DialogTitle>Import an RFQ</DialogTitle>
          <DialogDescription>
            Any layout works — letterheads, serial numbers and your buyer&apos;s own column names are fine. Nothing is
            created until you confirm.
          </DialogDescription>
          <Stepper step={step} canGo={(i) => i === 0 || (!!file && (i < 2 || mappingReady))} onGo={setStep} />
        </DialogHeader>

        <DialogBody className="space-y-4">
          {step === 0 && (
            <UploadStep
              file={file}
              dragging={dragging}
              error={fileError}
              inputRef={inputRef}
              onDrag={setDragging}
              onFile={acceptFile}
            />
          )}

          {step > 0 && file && (
            <FileStrip
              file={file}
              data={data}
              pending={preview.isPending}
              onReplace={() => {
                setStep(0);
                window.setTimeout(() => inputRef.current?.click(), 0);
              }}
            />
          )}

          {step === 1 && !data && preview.isPending && <ReadingPanel />}

          <FormError message={preview.error} />

          {step === 1 && data && (
            <MappingStep
              data={data}
              uoms={uoms.data ?? []}
              defaultUomId={defaultUomId}
              onDefaultUom={setDefaultUomId}
              onSheet={(i) => {
                setSheetIndex(i);
                setHeaderRow(null);
                setColumnMap(null);
              }}
              onHeaderRow={(r) => {
                setHeaderRow(r);
                setColumnMap(null);
              }}
              onField={(field, index) => {
                const next: ColumnMap = { ...data.columnMap };
                // A column feeds one field: taking it moves it.
                for (const [f, i] of Object.entries(next)) if (i === index) delete next[f as Field];
                if (index === null) delete next[field];
                else next[field] = index;
                setColumnMap(next);
                if (headerRow === null && data.headerRow) setHeaderRow(data.headerRow);
                if (sheetIndex === null) setSheetIndex(data.sheetIndex);
              }}
              onResetDetection={() => {
                setColumnMap(null);
                setHeaderRow(null);
                setSheetIndex(null);
              }}
            />
          )}

          {step === 2 && data && (
            <ReviewStep
              data={data}
              sourceName={sourceName}
              referenceNumber={referenceNumber}
              subject={subject}
              onSourceName={setSourceName}
              onReferenceNumber={setReferenceNumber}
              onSubject={setSubject}
              sourceError={doImport.fieldErrors.externalSourceName}
            />
          )}

          <FormError message={doImport.error && !doImport.fieldErrors.externalSourceName ? doImport.error : null} />
        </DialogBody>

        <DialogFooter className="sm:items-center">
          {step === 0 ? (
            <Button variant="ghost" className="sm:mr-auto" onClick={downloadSample}>
              <Download />
              Sample file
            </Button>
          ) : (
            <Button variant="ghost" className="sm:mr-auto" onClick={() => setStep(step - 1)} disabled={doImport.isPending}>
              <ArrowLeft />
              Back
            </Button>
          )}
          <Button variant="outline" onClick={() => setOpen(false)} disabled={doImport.isPending}>
            Cancel
          </Button>
          {step === 1 && (
            <Button onClick={() => setStep(2)} disabled={!mappingReady || preview.isPending} data-testid="import-rfq-next">
              Review {data && data.rowCount > 0 ? `${data.rowCount} item${data.rowCount === 1 ? "" : "s"}` : ""}
              <ArrowRight />
            </Button>
          )}
          {step === 2 && (
            <Button
              onClick={runImport}
              disabled={blocking || preview.isPending || doImport.isPending || !sourceName.trim()}
              data-testid="import-rfq-confirm"
            >
              {doImport.isPending ? <Loader2 className="animate-spin" /> : <Check />}
              {doImport.isPending ? "Importing..." : "Confirm Import"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------------------------------------- Stepper */

function Stepper({
  step,
  canGo,
  onGo,
}: {
  step: number;
  canGo: (i: number) => boolean;
  onGo: (i: number) => void;
}) {
  return (
    <ol className="mt-2 flex items-center gap-2" aria-label="Import steps">
      {STEPS.map((label, i) => {
        const done = i < step;
        const current = i === step;
        return (
          <li key={label} className="flex min-w-0 flex-1 items-center gap-2">
            <button
              type="button"
              disabled={!canGo(i) || current}
              onClick={() => onGo(i)}
              className="flex min-w-0 items-center gap-2 rounded-md text-left disabled:cursor-default"
              aria-current={current ? "step" : undefined}
            >
              <span
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold",
                  current && "bg-primary text-primary-foreground",
                  done && "bg-success text-success-foreground",
                  !current && !done && "bg-muted text-muted-foreground",
                )}
              >
                {done ? <Check className="size-3.5" /> : i + 1}
              </span>
              <span
                className={cn(
                  "truncate text-[13px]",
                  current ? "font-semibold text-foreground" : "hidden text-muted-foreground sm:inline",
                )}
              >
                {label}
              </span>
            </button>
            {i < STEPS.length - 1 && <span className="h-px min-w-4 flex-1 bg-border" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}

/* --------------------------------------------------------------- Step 1 */

function UploadStep({
  file,
  dragging,
  error,
  inputRef,
  onDrag,
  onFile,
}: {
  file: File | null;
  dragging: boolean;
  error: string | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onDrag: (v: boolean) => void;
  onFile: (f: File | undefined | null) => void;
}) {
  return (
    <div className="space-y-4">
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          onDrag(true);
        }}
        onDragLeave={() => onDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          onDrag(false);
          onFile(e.dataTransfer.files?.[0]);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragging ? "border-primary bg-primary-subtle" : "border-border bg-muted/30 hover:border-primary/50 hover:bg-muted/60",
        )}
        data-testid="import-rfq-dropzone"
      >
        <span className="flex size-14 items-center justify-center rounded-2xl bg-primary-subtle text-primary-subtle-foreground">
          <Upload className="size-6" />
        </span>
        <div>
          <p className="text-[15px] font-semibold text-foreground">
            {file ? file.name : "Drop the RFQ file here, or click to choose"}
          </p>
          <p className="mt-1 text-caption text-muted-foreground">
            Excel (.xlsx, .xls) or CSV · up to 10 MB
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xlsm,.xls,.csv"
          className="hidden"
          data-testid="import-rfq-file"
          onChange={(e) => {
            onFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>
      {error && (
        <p className="text-[13px] text-destructive" role="alert">
          {error}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        {[
          {
            icon: Wand2,
            title: "Finds the table itself",
            text: "Letterheads, RFQ numbers and blank rows above the items are skipped.",
          },
          {
            icon: Sparkles,
            title: "Understands Indian headings",
            text: "Particulars, Name of Item, Qty., Per, Req. Qty, UoM, Rate, Make…",
          },
          {
            icon: History,
            title: "Remembers your layouts",
            text: "Map a buyer's columns once — their next file maps itself.",
          },
        ].map(({ icon: Icon, title, text }) => (
          <div key={title} className="flex gap-3 rounded-lg border border-border p-3">
            <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
            <div>
              <p className="text-[13px] font-medium text-foreground">{title}</p>
              <p className="mt-0.5 text-caption text-muted-foreground">{text}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FileStrip({
  file,
  data,
  pending,
  onReplace,
}: {
  file: File;
  data: Preview | undefined;
  pending: boolean;
  onReplace: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/30 px-3 py-2.5">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-success-subtle text-success-subtle-foreground">
        <FileSpreadsheet className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13.5px] font-medium text-foreground">{file.name}</p>
        <p className="text-caption text-muted-foreground">
          {formatBytes(file.size)}
          {data?.sheetNames.length ? ` · sheet "${data.sheetNames[data.sheetIndex]}"` : ""}
          {data?.headerRow ? ` · headings on row ${data.headerRow}` : ""}
        </p>
      </div>
      {pending && (
        <span className="inline-flex items-center gap-1.5 text-caption text-muted-foreground" role="status">
          <Loader2 className="size-3.5 animate-spin" /> Reading…
        </span>
      )}
      <Button variant="ghost" size="sm" onClick={onReplace}>
        <RefreshCw />
        Replace
      </Button>
    </div>
  );
}

function ReadingPanel() {
  const [slow, setSlow] = React.useState(false);
  React.useEffect(() => {
    const t = window.setTimeout(() => setSlow(true), 3000);
    return () => window.clearTimeout(t);
  }, []);
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border px-6 py-10 text-center" role="status">
      <Loader2 className="size-6 animate-spin text-primary" />
      <p className="text-[14px] font-medium text-foreground">Reading your file…</p>
      <p className="max-w-md text-caption text-muted-foreground">
        {slow
          ? "Some columns weren't recognised, so the AI is reading them. On a local model this can take up to a minute."
          : "Finding the item table and matching its columns."}
      </p>
    </div>
  );
}

/* --------------------------------------------------------------- Step 2 */

function LayoutBanner({ data, onResetDetection }: { data: Preview; onResetDetection: () => void }) {
  const mapped = data.columns.filter((c) => c.columnIndex !== null).length;
  if (data.missingRequired.length > 0) {
    const names = data.columns.filter((c) => data.missingRequired.includes(c.field)).map((c) => c.label);
    return (
      <Banner tone="warning" icon={AlertTriangle} title={`Tell us which column holds: ${names.join(", ")}`}>
        Pick them below. If the headings aren&apos;t on row {data.headerRow ?? 1}, change the heading row first.
      </Banner>
    );
  }
  if (data.layoutSource === "saved") {
    return (
      <Banner tone="success" icon={History} title="Recognised a layout you've imported before">
        The saved mapping was applied. Change anything below and it will be updated when you import.
      </Banner>
    );
  }
  if (data.layoutSource === "manual") {
    return (
      <Banner tone="info" icon={Check} title="Using your mapping">
        It will be saved when you import, so the next file with these headings maps itself.{" "}
        <button type="button" className="font-medium underline underline-offset-2" onClick={onResetDetection}>
          Detect again
        </button>
      </Banner>
    );
  }
  const assisted = data.columns.filter((c) => c.match === "values" || c.match === "ai" || c.match === "llm").length;
  return (
    <Banner tone="success" icon={Sparkles} title={`Matched ${mapped} column${mapped === 1 ? "" : "s"} automatically`}>
      {assisted > 0
        ? `${assisted} of them were worked out from the values in the column or with AI — check those before you continue.`
        : "Check the matches below — especially any marked “Guess”."}
    </Banner>
  );
}

function Banner({
  tone,
  icon: Icon,
  title,
  children,
}: {
  tone: "success" | "warning" | "info";
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex gap-3 rounded-lg px-3.5 py-3",
        tone === "success" && "bg-success-subtle text-success-subtle-foreground",
        tone === "warning" && "bg-warning-subtle text-warning-subtle-foreground",
        tone === "info" && "bg-info-subtle text-info-subtle-foreground",
      )}
      data-testid="import-rfq-banner"
    >
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0">
        <p className="text-[13.5px] font-semibold">{title}</p>
        <p className="mt-0.5 text-[12.5px] opacity-90">{children}</p>
      </div>
    </div>
  );
}

function MatchBadge({ match, confidence }: { match: procurementApi.RfqImportColumn["match"]; confidence: number }) {
  if (!match) return null;
  if (match === "saved") return <Badge variant="success">Saved</Badge>;
  if (match === "manual") return <Badge variant="info">Your choice</Badge>;
  if (match === "exact") return <Badge variant="success">Exact</Badge>;
  if (match === "values") return <Badge variant="info">From values</Badge>;
  if (match === "ai")
    return (
      <Badge variant="ai">
        <Sparkles /> Suggested by AI
      </Badge>
    );
  if (match === "llm")
    return (
      <Badge variant="ai">
        <Sparkles /> AI guess · check
      </Badge>
    );
  if (confidence >= 75) return <Badge variant="info">Close match</Badge>;
  return <Badge variant="warning">Guess</Badge>;
}

function MappingStep({
  data,
  uoms,
  defaultUomId,
  onDefaultUom,
  onSheet,
  onHeaderRow,
  onField,
  onResetDetection,
}: {
  data: Preview;
  uoms: { id: string; code: string; name: string }[];
  defaultUomId: string | null;
  onDefaultUom: (id: string | null) => void;
  onSheet: (i: number) => void;
  onHeaderRow: (r: number) => void;
  onField: (field: Field, index: number | null) => void;
  onResetDetection: () => void;
}) {
  const fieldByColumn = new Map<number, Field>();
  for (const [f, i] of Object.entries(data.columnMap)) if (i !== undefined) fieldByColumn.set(i, f as Field);
  const labelOf = (f: Field) => data.columns.find((c) => c.field === f)?.label ?? f;
  const sampleFor = (index: number) =>
    data.sampleRows.map((r) => r[index]).find((v) => v && v.trim()) ?? "";
  const unitProblem = data.errors.some((e) => /unit/i.test(e));

  return (
    <div className="space-y-4" data-testid="import-rfq-mapping">
      <LayoutBanner data={data} onResetDetection={onResetDetection} />

      <div className="grid gap-3 sm:grid-cols-3">
        {data.sheetNames.length > 1 && (
          <div className="space-y-1.5">
            <Label>Sheet</Label>
            <Select value={String(data.sheetIndex)} onValueChange={(v) => onSheet(Number(v))}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {data.sheetNames.map((name, i) => (
                  <SelectItem key={i} value={String(i)}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="space-y-1.5">
          <Label>Column headings are on row</Label>
          <Select value={String(data.headerRow ?? 1)} onValueChange={(v) => onHeaderRow(Number(v))}>
            <SelectTrigger className="w-full" data-testid="import-rfq-header-row">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Array.from({ length: 30 }, (_, i) => i + 1).map((n) => (
                <SelectItem key={n} value={String(n)}>
                  Row {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label className={cn(unitProblem && !defaultUomId && "text-warning-subtle-foreground")}>
            Default unit {unitProblem && !defaultUomId && "· needed"}
          </Label>
          <Select value={defaultUomId ?? NONE} onValueChange={(v) => onDefaultUom(v === NONE ? null : v)}>
            <SelectTrigger
              className={cn("w-full", unitProblem && !defaultUomId && "border-warning ring-2 ring-warning/30")}
              data-testid="import-rfq-default-uom"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>None — every line needs a unit</SelectItem>
              {uoms.map((u) => (
                <SelectItem key={u.id} value={u.id}>
                  {u.name} ({u.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        {/* Field → column */}
        <div className="rounded-lg border border-border lg:col-span-2">
          <div className="border-b border-border px-3.5 py-2.5">
            <p className="text-[13.5px] font-semibold text-foreground">Your RFQ fields</p>
            <p className="text-caption text-muted-foreground">Which column of the file fills each one</p>
          </div>
          <ul className="divide-y divide-border">
            {data.columns.map((c) => (
              <li key={c.field} className="space-y-1.5 px-3.5 py-2.5" data-testid={`map-${c.field}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    <span className={cn("size-2.5 rounded-full", FIELD_DOT[c.field])} aria-hidden="true" />
                    <span className="text-[13px] font-medium text-foreground">
                      {c.label}
                      {c.required && <span className="text-destructive"> *</span>}
                    </span>
                  </span>
                  <MatchBadge match={c.match} confidence={c.confidence} />
                </div>
                <Select
                  value={c.columnIndex === null ? NONE : String(c.columnIndex)}
                  onValueChange={(v) => onField(c.field, v === NONE ? null : Number(v))}
                >
                  <SelectTrigger
                    className={cn(
                      "h-8 w-full text-[13px]",
                      c.required && c.columnIndex === null && "border-warning ring-2 ring-warning/30",
                    )}
                    aria-label={`Column for ${c.label}`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>— Not in this file —</SelectItem>
                    {data.headers.map((h, i) => {
                      const takenBy = fieldByColumn.get(i);
                      const sample = sampleFor(i);
                      return (
                        <SelectItem key={i} value={String(i)}>
                          <span className="font-mono text-[11.5px] text-muted-foreground">{columnLetter(i)}</span>{" "}
                          {h}
                          {sample && <span className="text-muted-foreground"> · e.g. {sample.slice(0, 24)}</span>}
                          {takenBy && takenBy !== c.field && (
                            <span className="text-muted-foreground"> (now {labelOf(takenBy)})</span>
                          )}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                {c.reason && (c.match === "values" || c.match === "ai" || c.match === "llm") ? (
                  <p className="flex items-start gap-1 text-[11.5px] text-ai-subtle-foreground">
                    <Sparkles className="mt-px size-3 shrink-0" />
                    <span>Because {c.reason}</span>
                  </p>
                ) : (
                  <p className="text-[11.5px] text-muted-foreground">{FIELD_HINT[c.field]}</p>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* The file itself, with the mapping painted on */}
        <div className="min-w-0 rounded-lg border border-border lg:col-span-3">
          <div className="border-b border-border px-3.5 py-2.5">
            <p className="text-[13.5px] font-semibold text-foreground">Your file</p>
            <p className="text-caption text-muted-foreground">
              Headings from row {data.headerRow ?? 1} and the first lines under them
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-max border-collapse text-[12.5px]">
              <thead>
                <tr>
                  {data.headers.map((h, i) => {
                    const f = fieldByColumn.get(i);
                    return (
                      <th key={i} className="border-b border-border px-2.5 pt-2 pb-1.5 text-left align-bottom font-normal">
                        <span className="block font-mono text-[10.5px] text-muted-foreground">{columnLetter(i)}</span>
                        {f ? (
                          <span
                            className={cn(
                              "mt-1 inline-flex rounded px-1.5 py-0.5 text-[11px] font-semibold ring-1",
                              FIELD_TONE[f],
                            )}
                          >
                            {labelOf(f)}
                          </span>
                        ) : (
                          <span className="mt-1 inline-flex rounded px-1.5 py-0.5 text-[11px] text-muted-foreground">
                            ignored
                          </span>
                        )}
                        <span className="mt-1 block max-w-[180px] truncate font-semibold text-foreground" title={h}>
                          {h}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {data.sampleRows.length === 0 ? (
                  <tr>
                    <td colSpan={Math.max(data.headers.length, 1)} className="px-3 py-4 text-muted-foreground">
                      No lines under this heading row.
                    </td>
                  </tr>
                ) : (
                  data.sampleRows.map((row, r) => (
                    <tr key={r} className="border-b border-border last:border-0">
                      {data.headers.map((_h, i) => (
                        <td
                          key={i}
                          className={cn(
                            "max-w-[200px] truncate px-2.5 py-1.5",
                            fieldByColumn.has(i) ? "text-foreground" : "text-muted-foreground/70",
                          )}
                          title={row[i]}
                        >
                          {row[i] || " "}
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <Issues data={data} />
    </div>
  );
}

/* --------------------------------------------------------------- Step 3 */

function ReviewStep({
  data,
  sourceName,
  referenceNumber,
  subject,
  onSourceName,
  onReferenceNumber,
  onSubject,
  sourceError,
}: {
  data: Preview;
  sourceName: string;
  referenceNumber: string;
  subject: string;
  onSourceName: (v: string) => void;
  onReferenceNumber: (v: string) => void;
  onSubject: (v: string) => void;
  sourceError?: string;
}) {
  const estimated = data.rows.reduce((sum, r) => sum + r.quantity * r.expectedPrice, 0);
  return (
    <div className="space-y-4" data-testid="import-rfq-review">
      <div className="grid gap-3.5 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="import-source">
            Received from <span className="text-destructive">*</span>
          </Label>
          <Input
            id="import-source"
            placeholder="e.g. Tata Projects, GeM, IndiaMART"
            value={sourceName}
            onChange={(e) => onSourceName(e.target.value)}
            aria-invalid={!!sourceError}
            data-testid="import-rfq-source"
          />
          {sourceError && <p className="text-caption text-destructive">{sourceError}</p>}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="import-ref">Their RFQ / enquiry no.</Label>
          <Input
            id="import-ref"
            placeholder="If the file has one"
            value={referenceNumber}
            onChange={(e) => onReferenceNumber(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="import-subject">Subject</Label>
          <Input
            id="import-subject"
            placeholder={sourceName ? `Imported from ${sourceName}` : "Optional"}
            value={subject}
            onChange={(e) => onSubject(e.target.value)}
          />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Items" value={String(data.rowCount)} tone={data.rowCount > 0 ? "success" : "warning"} />
        <Stat label="Needs attention" value={String(data.errors.length)} tone={data.errors.length ? "warning" : "success"} />
        <Stat label="Estimated value" value={estimated > 0 ? formatCurrency(estimated) : "—"} tone="neutral" />
      </div>

      <Issues data={data} />

      <div className="overflow-hidden rounded-lg border border-border">
        <div className="max-h-[340px] overflow-auto">
          <table className="w-full text-[13px]">
            <thead className="sticky top-0 bg-muted text-left text-[12px] text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Row</th>
                <th className="px-3 py-2 font-medium">Description</th>
                <th className="px-3 py-2 text-right font-medium">Qty</th>
                <th className="px-3 py-2 font-medium">Unit</th>
                <th className="px-3 py-2 text-right font-medium">Expected rate</th>
                <th className="px-3 py-2 font-medium">Remarks</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                    No items yet — fix the points above.
                  </td>
                </tr>
              ) : (
                data.rows.map((r) => (
                  <tr key={r.sourceRow} className="border-t border-border">
                    <td className="px-3 py-2 font-mono text-[11.5px] text-muted-foreground">{r.sourceRow}</td>
                    <td className="max-w-[320px] px-3 py-2 font-medium text-foreground">{r.description}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.quantity}</td>
                    <td className="px-3 py-2">
                      <Badge variant="neutral">{r.uomCode}</Badge>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {r.expectedPrice > 0 ? formatCurrency(r.expectedPrice) : "—"}
                    </td>
                    <td className="max-w-[240px] truncate px-3 py-2 text-muted-foreground" title={r.remarks ?? ""}>
                      {r.remarks || "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-caption text-muted-foreground">
        The RFQ is created as a draft. You can link lines to your products and pick suppliers before sending it.
      </p>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: "success" | "warning" | "neutral" }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2.5">
      <p className="text-caption text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 flex items-center gap-1.5 text-[17px] font-semibold tabular-nums",
          tone === "success" && "text-foreground",
          tone === "warning" && "text-warning-subtle-foreground",
          tone === "neutral" && "text-foreground",
        )}
      >
        {tone === "success" && <CheckCircle2 className="size-4 text-success" />}
        {tone === "warning" && <AlertTriangle className="size-4" />}
        {value}
      </p>
    </div>
  );
}

function Issues({ data }: { data: Preview }) {
  const errors = data.errors.filter((e) => !(data.missingRequired.length && /Couldn't tell which column/.test(e)));
  if (errors.length === 0 && data.warnings.length === 0) return null;
  return (
    <div className="space-y-2" data-testid="import-rfq-issues">
      {errors.length > 0 && (
        <div className="rounded-lg border border-destructive/30 bg-destructive-subtle px-3.5 py-2.5 text-destructive-subtle-foreground">
          <p className="flex items-center gap-1.5 text-[13px] font-semibold">
            <AlertTriangle className="size-4" /> Fix before importing
          </p>
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-[12.5px]">
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      {data.warnings.length > 0 && (
        <div className="rounded-lg border border-border bg-muted/40 px-3.5 py-2.5 text-muted-foreground">
          <p className="text-[13px] font-semibold text-foreground">Good to know</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-[12.5px]">
            {data.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

