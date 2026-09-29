import { formatMoney, formatPercent, type TaxBreakdownRow } from "@/lib/domain/money";
import { cn } from "@/lib/utils";
import type { MoneyTotals } from "@/types";

/**
 * Pure presentation of a document's money block. Every number here is read
 * straight off the API's `MoneyTotals` shape (or the same shape produced
 * locally by `computeDocumentTotals` while a form is still a draft) — this
 * component never multiplies, splits or rounds anything itself (C13).
 *
 * `taxRows`, when given, renders the per-GST-rate breakdown table beneath the
 * totals (the `taxRows` a detail endpoint returns, or `taxBreakdown()` for a
 * form that hasn't been saved yet).
 */
export function TaxSummary({
  money,
  taxRows,
  className,
}: {
  money: MoneyTotals;
  taxRows?: TaxBreakdownRow[];
  className?: string;
}) {
  const rows: Array<{ label: string; value: number }> = [
    { label: "Subtotal", value: money.subtotal },
    { label: "Discount", value: -money.discountAmount },
    { label: "Taxable Value", value: money.taxableValue },
  ];

  if (money.isInterState) {
    rows.push({ label: "IGST", value: money.igstAmount });
  } else {
    rows.push({ label: "CGST", value: money.cgstAmount }, { label: "SGST", value: money.sgstAmount });
  }
  if (money.cessAmount) rows.push({ label: "Cess", value: money.cessAmount });
  rows.push({ label: "Freight", value: money.freightAmount });
  if (money.otherCharges) rows.push({ label: "Other Charges", value: money.otherCharges });
  rows.push({ label: "Round Off", value: money.roundOff });

  return (
    <div className={cn("space-y-4", className)}>
      <div className="space-y-1.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center justify-between text-[13px]">
            <span className="text-muted-foreground">{row.label}</span>
            <span className="font-medium text-foreground tabular">{formatMoney(row.value, true)}</span>
          </div>
        ))}
        <div className="flex items-center justify-between border-t border-border pt-2 text-[14px]">
          <span className="font-semibold text-foreground">Total</span>
          <span className="text-[19px] font-semibold tracking-[-0.02em] text-foreground tabular">
            {formatMoney(money.totalAmount)}
          </span>
        </div>
      </div>

      {taxRows && taxRows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-left text-muted-foreground">
                <th className="px-3 py-1.5 font-medium">GST %</th>
                <th className="px-3 py-1.5 text-right font-medium">Taxable</th>
                {money.isInterState ? (
                  <th className="px-3 py-1.5 text-right font-medium">IGST</th>
                ) : (
                  <>
                    <th className="px-3 py-1.5 text-right font-medium">CGST</th>
                    <th className="px-3 py-1.5 text-right font-medium">SGST</th>
                  </>
                )}
                <th className="px-3 py-1.5 text-right font-medium">Total Tax</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {taxRows.map((row) => (
                <tr key={row.gstRate}>
                  <td className="px-3 py-1.5 text-foreground tabular">{formatPercent(row.gstRate)}</td>
                  <td className="px-3 py-1.5 text-right text-muted-foreground tabular">
                    {formatMoney(row.taxableValue, true)}
                  </td>
                  {money.isInterState ? (
                    <td className="px-3 py-1.5 text-right text-muted-foreground tabular">
                      {formatMoney(row.igstAmount, true)}
                    </td>
                  ) : (
                    <>
                      <td className="px-3 py-1.5 text-right text-muted-foreground tabular">
                        {formatMoney(row.cgstAmount, true)}
                      </td>
                      <td className="px-3 py-1.5 text-right text-muted-foreground tabular">
                        {formatMoney(row.sgstAmount, true)}
                      </td>
                    </>
                  )}
                  <td className="px-3 py-1.5 text-right font-medium text-foreground tabular">
                    {formatMoney(row.totalTax, true)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
