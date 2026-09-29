import { FileSearch, PackageSearch, ShieldCheck, Users } from "lucide-react";

import { LogoMark } from "@/components/common/logo";
import { WarehouseIllustration } from "@/components/common/warehouse-illustration";

const VALUE_PROPS = [
  {
    icon: Users,
    title: "Manage Suppliers",
    description: "RFQs, quotations and purchase orders in one place.",
  },
  {
    icon: PackageSearch,
    title: "Track Inventory",
    description: "Live stock across every godown, updated on each receipt.",
  },
  {
    icon: FileSearch,
    title: "AI Document Processing",
    description: "Read quotations and invoices from Excel, PDF or a photo.",
  },
  {
    icon: ShieldCheck,
    title: "Built for Indian Business",
    description: "GST, HSN, E-way bill and multi-godown out of the box.",
  },
];

export function LoginBrandPanel() {
  return (
    <aside className="relative hidden overflow-hidden bg-sidebar lg:flex lg:w-[52%] lg:flex-col xl:w-[54%]">
      {/* Depth: soft radial wash + fine grid */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(110% 80% at 12% -5%, oklch(0.35 0.08 264) 0%, transparent 58%), radial-gradient(90% 65% at 105% 105%, oklch(0.31 0.075 248) 0%, transparent 62%)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.05]"
        style={{
          backgroundImage:
            "linear-gradient(to right, white 1px, transparent 1px), linear-gradient(to bottom, white 1px, transparent 1px)",
          backgroundSize: "56px 56px",
        }}
      />

      {/* Warehouse line art along the bottom, faded into the panel at both ends */}
      <div className="pointer-events-none absolute inset-x-0 -bottom-4 z-0 text-white/20 [mask-image:linear-gradient(to_top,transparent_2%,black_26%,black_38%,transparent_95%)]">
        <WarehouseIllustration />
      </div>

      {/* Scrim so the closing line stays readable over the line art */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[5] h-36 bg-gradient-to-t from-sidebar via-sidebar/70 to-transparent" />

      <div className="relative z-10 flex h-full flex-col p-10 xl:p-14">
        <div className="flex items-center gap-3">
          <LogoMark className="size-9" />
          <span className="text-[19px] font-semibold tracking-[-0.02em] text-white">
            InventoryAI
          </span>
        </div>

        <div className="flex flex-1 flex-col justify-center py-10">
          <div className="max-w-[470px]">
            <h1 className="text-[36px] leading-[1.16] font-semibold tracking-[-0.03em] text-white xl:text-[42px]">
              Smarter Procurement
              <br />
              Better Inventory
              <br />
              <span className="text-white/45">Stronger Business</span>
            </h1>

            <ul className="mt-9 space-y-4.5 xl:mt-11">
              {VALUE_PROPS.map(({ icon: Icon, title, description }) => (
                <li key={title} className="flex items-start gap-3.5">
                  <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.07] ring-1 ring-white/[0.12]">
                    <Icon className="size-4 text-white/85" strokeWidth={1.9} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[14px] font-medium text-white">
                      {title}
                    </span>
                    <span className="block text-[13px] leading-snug text-white/55">
                      {description}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <p className="text-[13px] font-medium tracking-wide text-white/45">
          From Purchase to Inventory, All in One Place
        </p>
      </div>
    </aside>
  );
}
