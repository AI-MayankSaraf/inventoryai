import Link from "next/link";
import { ChevronRight } from "lucide-react";

import type { ProcurementStat } from "@/types";

export function ProcurementOverview({ stats }: { stats: ProcurementStat[] }) {
  return (
    <ul className="flex h-full flex-col divide-y divide-border">
      {stats.map((stat) => (
        <li key={stat.key} className="flex-1">
          <Link
            href={stat.href}
            className="flex h-full items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/55"
          >
            <span className="w-11 shrink-0 text-[20px] leading-none font-semibold text-foreground tabular">
              {stat.value}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-medium text-foreground">
                {stat.label}
              </span>
              <span className="block text-caption text-muted-foreground">{stat.hint}</span>
            </span>
            <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  );
}
