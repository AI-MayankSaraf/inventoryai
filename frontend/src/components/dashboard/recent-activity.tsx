import {
  AlertTriangle,
  ArrowLeftRight,
  FileText,
  PackageCheck,
  ReceiptText,
  Send,
  Sparkles,
  Undo2,
  type LucideIcon,
} from "lucide-react";

import type { ActivityItem } from "@/types";
import { cn } from "@/lib/utils";

const ICONS: Record<ActivityItem["type"], { icon: LucideIcon; className: string }> = {
  po: { icon: FileText, className: "bg-primary-subtle text-primary-subtle-foreground" },
  grn: { icon: PackageCheck, className: "bg-success-subtle text-success-subtle-foreground" },
  rfq: { icon: Send, className: "bg-info-subtle text-info-subtle-foreground" },
  quotation: { icon: Sparkles, className: "bg-ai-subtle text-ai-subtle-foreground" },
  invoice: { icon: ReceiptText, className: "bg-info-subtle text-info-subtle-foreground" },
  return: { icon: Undo2, className: "bg-warning-subtle text-warning-subtle-foreground" },
  transfer: { icon: ArrowLeftRight, className: "bg-muted text-muted-foreground" },
  alert: {
    icon: AlertTriangle,
    className: "bg-destructive-subtle text-destructive-subtle-foreground",
  },
};

export function RecentActivity({ items }: { items: ActivityItem[] }) {
  return (
    <ul className="divide-y divide-border">
      {items.map((item) => {
        const { icon: Icon, className } = ICONS[item.type];
        return (
          <li key={item.id} className="flex items-start gap-3 px-4 py-3">
            <span
              className={cn(
                "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg",
                className,
              )}
            >
              <Icon className="size-3.5" strokeWidth={2} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13.5px] font-medium text-foreground">
                {item.title}
              </p>
              <p className="truncate text-caption text-muted-foreground">{item.detail}</p>
            </div>
            <span className="shrink-0 text-caption whitespace-nowrap text-muted-foreground">
              {item.time}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
