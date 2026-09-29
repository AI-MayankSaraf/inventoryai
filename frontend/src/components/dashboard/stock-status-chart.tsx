"use client";

import * as React from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type { StockStatusSlice } from "@/types";
import { formatNumber } from "@/lib/format";

function ChartTooltip({
  active,
  payload,
  total,
}: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; payload?: StockStatusSlice }>;
  total: number;
}) {
  if (!active || !payload?.length) return null;
  const slice = payload[0].payload as StockStatusSlice;
  const share = total > 0 ? Math.round((slice.value / total) * 100) : 0;

  return (
    <div className="rounded-md border border-border bg-popover px-2.5 py-2 shadow-float">
      <p className="flex items-center gap-2 text-[12.5px] font-medium text-foreground">
        <span
          className="size-2 shrink-0 rounded-[2px]"
          style={{ backgroundColor: slice.color }}
        />
        {slice.label}
      </p>
      <p className="mt-0.5 pl-4 text-[12px] text-muted-foreground tabular">
        {formatNumber(slice.value)} SKUs · {share}%
      </p>
    </div>
  );
}

export function StockStatusChart({ data }: { data: StockStatusSlice[] }) {
  const total = data.reduce((sum, slice) => sum + slice.value, 0);

  return (
    <div className="px-4 py-4">
      <div className="relative mx-auto h-[188px] w-full max-w-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="label"
              innerRadius={62}
              outerRadius={88}
              paddingAngle={2}
              startAngle={90}
              endAngle={-270}
              stroke="var(--card)"
              strokeWidth={2}
              isAnimationActive={false}
            >
              {data.map((slice) => (
                <Cell key={slice.key} fill={slice.color} />
              ))}
            </Pie>
            <Tooltip
              content={<ChartTooltip total={total} />}
              cursor={false}
              wrapperStyle={{ outline: "none" }}
            />
          </PieChart>
        </ResponsiveContainer>

        {/* Hero number in the hole */}
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[24px] leading-none font-semibold tracking-[-0.02em] text-foreground tabular">
            {formatNumber(total)}
          </span>
          <span className="mt-1 text-caption text-muted-foreground">Total SKUs</span>
        </div>
      </div>

      {/* Legend — labels + counts + share carry identity so colour is never the only cue */}
      <ul className="mx-auto mt-4 max-w-[340px] space-y-2">
        {data.map((slice) => {
          const share = total > 0 ? Math.round((slice.value / total) * 100) : 0;
          return (
            <li key={slice.key} className="flex items-center gap-2.5 text-[13px]">
              <span
                className="size-2.5 shrink-0 rounded-[3px]"
                style={{ backgroundColor: slice.color }}
                aria-hidden="true"
              />
              <span className="text-foreground">{slice.label}</span>
              <span className="ml-auto text-muted-foreground tabular">
                {formatNumber(slice.value)}
              </span>
              <span className="w-9 text-right font-medium text-foreground tabular">
                {share}%
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
