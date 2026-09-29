"use client";

import * as React from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

/** Compact filter dropdown used in every table toolbar. */
export function FilterSelect({
  placeholder,
  options,
  className,
  defaultValue = "all",
  value,
  onValueChange,
}: {
  placeholder: string;
  options: string[];
  className?: string;
  defaultValue?: string;
  value?: string;
  onValueChange?: (value: string) => void;
}) {
  return (
    <Select
      defaultValue={value === undefined ? defaultValue : undefined}
      value={value}
      onValueChange={onValueChange}
    >
      <SelectTrigger size="sm" className={cn("w-[152px]", className)}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{placeholder}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option} value={option}>
            {option}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
