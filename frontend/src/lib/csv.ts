/**
 * Download rows as a CSV file. Excel-friendly: a UTF-8 byte-order mark (so
 * "₹" and Hindi names survive), CRLF line ends, and quoting only where a
 * value needs it.
 */
export function downloadCsv(name: string, header: string[], rows: unknown[][]): void {
  const cell = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [header, ...rows].map((row) => row.map(cell).join(","));
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const day = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local time
  a.download = `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${day}.csv`;
  // Firefox ignores clicks on a detached anchor, and revoking the URL in the
  // same tick can cancel the download before the browser has read the blob.
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
