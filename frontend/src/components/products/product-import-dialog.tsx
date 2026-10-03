"use client";

import * as React from "react";
import { CircleCheck, Download, FileSpreadsheet, FileUp, Loader2, TriangleAlert } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { useApiMutation } from "@/hooks/use-api";
import {
  PRODUCT_IMPORT_ACCEPT,
  downloadProductImportTemplate,
  importProducts,
  previewProductImport,
} from "@/lib/api/catalog.api";
import { cn } from "@/lib/utils";

/**
 * Products / SKUs from Excel or CSV. The file is checked on the server
 * first and nothing is written until every row is clean; then it imports
 * whole, or not at all.
 */
export function ProductImportDialog({ onImported }: { onImported: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [file, setFile] = React.useState<File | null>(null);
  const [done, setDone] = React.useState<{ imported: number; newBrands: string[]; newCategories: string[] } | null>(
    null,
  );
  const preview = useApiMutation(previewProductImport);
  const run = useApiMutation(importProducts, {
    onSuccess: (result) => {
      setDone(result);
      onImported();
    },
  });
  const template = useApiMutation(downloadProductImportTemplate);

  function reset() {
    setFile(null);
    setDone(null);
    preview.reset();
    run.reset();
  }

  function choose(chosen: File | undefined) {
    if (!chosen) return;
    setFile(chosen);
    setDone(null);
    run.reset();
    void preview.run(chosen);
  }

  const data = preview.data;
  const ready = !!file && !!data && data.errorCount === 0 && data.rowCount > 0;

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)} data-testid="import-products">
        <FileUp />
        Import Excel
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (run.isPending) return;
          setOpen(next);
          if (!next) reset();
        }}
      >
        <DialogContent className="sm:max-w-[720px]">
          <DialogHeader>
            <DialogTitle>Import products from Excel</DialogTitle>
            <DialogDescription>
              One row per product: SKU, Product Name and Unit are required. Every row is checked before anything
              is saved.
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="space-y-4">
            {done ? (
              <Alert variant="success" data-testid="import-products-done">
                <CircleCheck />
                <AlertDescription>
                  Imported {done.imported} product{done.imported === 1 ? "" : "s"}.
                  {done.newBrands.length > 0 && ` New brands: ${done.newBrands.join(", ")}.`}
                  {done.newCategories.length > 0 && ` New categories: ${done.newCategories.join(", ")}.`}
                </AlertDescription>
              </Alert>
            ) : (
              <>
                <label
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    choose(e.dataTransfer.files[0]);
                  }}
                  className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-muted/40 px-6 py-6 text-center transition-colors hover:border-primary/45 hover:bg-primary-subtle/35"
                >
                  <input
                    type="file"
                    accept={PRODUCT_IMPORT_ACCEPT}
                    className="hidden"
                    data-testid="import-products-input"
                    onChange={(e) => {
                      const chosen = e.target.files?.[0];
                      e.target.value = "";
                      choose(chosen);
                    }}
                  />
                  <FileSpreadsheet className="size-5 text-muted-foreground" />
                  <span className="mt-2 text-[13.5px] font-medium text-foreground">
                    {file ? file.name : "Choose an Excel or CSV file"}
                  </span>
                  <span className="mt-0.5 text-caption text-muted-foreground">
                    {file ? "Click to choose a different file" : "Drag & drop here or click to browse (.xlsx, .xls, .csv)"}
                  </span>
                </label>

                {preview.isPending && (
                  <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" /> Checking the file...
                  </p>
                )}

                {data && !preview.isPending && (
                  <div className="space-y-3" data-testid="import-products-preview">
                    <div className="grid grid-cols-3 gap-3">
                      <Stat label="Rows found" value={data.rowCount} />
                      <Stat label="Ready to import" value={data.validCount} tone={data.validCount ? "success" : undefined} />
                      <Stat label="Need fixing" value={data.errorCount} tone={data.errorCount ? "warning" : "success"} />
                    </div>

                    {data.columns.some((c) => c.header) && (
                      <p className="text-caption text-muted-foreground">
                        Read from row {data.headerRow}:{" "}
                        {data.columns
                          .filter((c) => c.header)
                          .map((c) => (c.header === c.label ? c.label : `${c.label} ← "${c.header}"`))
                          .join(" · ")}
                      </p>
                    )}

                    {data.fileErrors.map((e) => (
                      <Alert key={e} variant="destructive">
                        <TriangleAlert />
                        <AlertDescription>{e}</AlertDescription>
                      </Alert>
                    ))}

                    {data.rowErrors.length > 0 && (
                      <div className="max-h-56 overflow-y-auto rounded-lg border border-border">
                        <table className="w-full text-[12.5px]" data-testid="import-products-errors">
                          <thead className="sticky top-0 bg-muted text-left text-muted-foreground">
                            <tr>
                              <th className="px-3 py-1.5 font-medium">Row</th>
                              <th className="px-3 py-1.5 font-medium">SKU</th>
                              <th className="px-3 py-1.5 font-medium">Problem</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-border">
                            {data.rowErrors.map((r) => (
                              <tr key={r.row}>
                                <td className="px-3 py-1.5 tabular">{r.row}</td>
                                <td className="px-3 py-1.5 font-mono">{r.sku || "—"}</td>
                                <td className="px-3 py-1.5 text-destructive">{r.errors.join("; ")}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {(data.newBrands.length > 0 || data.newCategories.length > 0) && data.errorCount === 0 && (
                      <p className="text-caption text-muted-foreground">
                        Will also create
                        {data.newBrands.length > 0 && ` brand${data.newBrands.length === 1 ? "" : "s"} ${data.newBrands.join(", ")}`}
                        {data.newBrands.length > 0 && data.newCategories.length > 0 && " and"}
                        {data.newCategories.length > 0 &&
                          ` categor${data.newCategories.length === 1 ? "y" : "ies"} ${data.newCategories.join(", ")}`}
                        .
                      </p>
                    )}

                    {data.errorCount > 0 && (
                      <p className="text-caption text-muted-foreground">
                        Fix these rows in the file and choose it again. Nothing is imported while any row has a
                        problem.
                      </p>
                    )}
                  </div>
                )}
              </>
            )}

            <FormError message={preview.error ?? run.error ?? template.error} />
          </DialogBody>

          <DialogFooter className="sm:items-center">
            <Button
              variant="ghost"
              className="sm:mr-auto"
              onClick={() => template.run(undefined)}
              disabled={template.isPending}
            >
              <Download />
              Template
            </Button>
            {done ? (
              <Button onClick={() => setOpen(false)}>Done</Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => setOpen(false)} disabled={run.isPending}>
                  Cancel
                </Button>
                <Button
                  onClick={() => file && run.run(file)}
                  disabled={!ready || run.isPending}
                  data-testid="import-products-confirm"
                >
                  {run.isPending ? <Loader2 className="animate-spin" /> : <FileUp />}
                  {run.isPending
                    ? "Importing..."
                    : `Import ${data?.validCount ? `${data.validCount} product${data.validCount === 1 ? "" : "s"}` : ""}`}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "success" | "warning" }) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border px-3 py-2",
        tone === "success" && "border-success/30 bg-success-subtle/40",
        tone === "warning" && "border-warning/40 bg-warning-subtle/40",
      )}
    >
      <p className="text-caption text-muted-foreground">{label}</p>
      <p className="text-[18px] font-semibold text-foreground tabular">{value}</p>
    </div>
  );
}
