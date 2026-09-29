import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * InventoryAI mark — an isometric carton (inventory) with an upward chevron
 * cut into the top face (growth / smarter buying).
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 36 36"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("size-9", className)}
      aria-hidden="true"
    >
      <rect width="36" height="36" rx="9" className="fill-primary" />
      {/* top face */}
      <path
        d="M18 7.5 28 12.75 18 18 8 12.75 18 7.5Z"
        className="fill-primary-foreground"
      />
      {/* left face */}
      <path
        d="M8 14.75v8.4L17 28v-8.4L8 14.75Z"
        className="fill-primary-foreground"
        opacity="0.55"
      />
      {/* right face */}
      <path
        d="M28 14.75v8.4L19 28v-8.4l9-4.85Z"
        className="fill-primary-foreground"
        opacity="0.8"
      />
      {/* tape seam */}
      <path
        d="M13 10.15 23 15.4"
        className="stroke-primary"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.35"
      />
    </svg>
  );
}

export function Logo({
  className,
  wordmarkClassName,
  markClassName,
  showWordmark = true,
}: {
  className?: string;
  wordmarkClassName?: string;
  markClassName?: string;
  showWordmark?: boolean;
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark className={cn("size-8", markClassName)} />
      {showWordmark && (
        <span
          className={cn(
            "text-[17px] font-semibold tracking-[-0.02em] text-foreground",
            wordmarkClassName,
          )}
        >
          Inventory<span className="text-primary">AI</span>
        </span>
      )}
    </div>
  );
}
