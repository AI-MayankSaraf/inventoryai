"use client";

import { useRouter } from "next/navigation";

import { SupplierFormDialog } from "@/components/suppliers/supplier-form-dialog";
import type { Supplier } from "@/types";

export function SupplierDetailActions({ supplier }: { supplier: Supplier }) {
  const router = useRouter();

  return (
    <SupplierFormDialog
      supplier={supplier}
      onSaved={() => router.push("/suppliers")}
    />
  );
}
