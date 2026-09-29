import { LogoMark } from "@/components/common/logo";

/**
 * Branded letterhead shown only in print output (`hidden print:flex`).
 *
 * Convention used across the app: a document a company ISSUES to another
 * party (RFQ, Purchase Order — sent to a supplier; Proforma reviews) prints
 * with the issuing/buyer company's letterhead, the same way a printed PO or
 * letter carries the sender's masthead in real business practice. GRNs and
 * internal records print a lighter "internal document" header instead of
 * a full letterhead, since they never leave the company.
 */
export function PrintHeader({
  company,
  gstin,
  address,
  email,
  phone,
  docLabel,
}: {
  company: string;
  gstin?: string | null;
  address?: string;
  email?: string;
  phone?: string;
  docLabel: string;
}) {
  return (
    <div className="hidden print:mb-6 print:flex print:items-start print:justify-between print:border-b-2 print:border-foreground print:pb-4">
      <div className="flex items-center gap-3">
        <LogoMark className="size-9" />
        <div>
          <p className="text-[16px] font-bold tracking-tight">{company}</p>
          {address && <p className="text-[11px] text-muted-foreground">{address}</p>}
          <p className="text-[11px] text-muted-foreground">
            {gstin && <>GSTIN: {gstin}</>}
            {gstin && (email || phone) && " · "}
            {email}
            {email && phone && " · "}
            {phone}
          </p>
        </div>
      </div>
      <div className="text-right">
        <p className="text-[13px] font-semibold uppercase tracking-wide text-muted-foreground">
          {docLabel}
        </p>
        <p className="text-[10.5px] text-muted-foreground">Printed {new Date().toLocaleDateString("en-IN")}</p>
      </div>
    </div>
  );
}
