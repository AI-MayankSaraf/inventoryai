"use client";

import * as React from "react";
import { FileSpreadsheet, FileText, ImageIcon, UploadCloud } from "lucide-react";

import { cn } from "@/lib/utils";

const ACCEPTED = [
  { icon: FileSpreadsheet, label: "Excel", ext: ".xlsx, .xls, .csv" },
  { icon: FileText, label: "PDF & Word", ext: ".pdf, .docx" },
  { icon: ImageIcon, label: "Photos", ext: ".jpg, .png, .webp" },
];

export function DocumentDropzone({
  onFiles,
}: {
  onFiles?: (files: File[]) => void;
}) {
  const [dragging, setDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        onFiles?.(Array.from(e.dataTransfer.files));
      }}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors outline-none",
        dragging
          ? "border-primary bg-primary-subtle/70"
          : "border-border bg-muted/40 hover:border-primary/45 hover:bg-primary-subtle/35",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".xlsx,.xls,.csv,.pdf,.docx,.jpg,.jpeg,.png,.webp"
        className="hidden"
        onChange={(e) => onFiles?.(Array.from(e.target.files ?? []))}
      />

      <span className="flex size-11 items-center justify-center rounded-xl bg-primary-subtle text-primary-subtle-foreground">
        <UploadCloud className="size-5" strokeWidth={1.9} />
      </span>
      <p className="mt-3 text-[15px] font-semibold text-foreground">
        Drop Excel, PDF, Word or an image here
      </p>
      <p className="mt-1 text-[13px] text-muted-foreground">
        or click to browse · up to 20 MB per file
      </p>

      <ul className="mt-5 flex flex-wrap items-center justify-center gap-2">
        {ACCEPTED.map(({ icon: Icon, label, ext }) => (
          <li
            key={label}
            className="flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5 text-left"
          >
            <Icon className="size-4 shrink-0 text-muted-foreground" strokeWidth={1.9} />
            <span>
              <span className="block text-[12.5px] font-medium text-foreground">{label}</span>
              <span className="block text-[11px] text-muted-foreground">{ext}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
