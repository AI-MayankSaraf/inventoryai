"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { CompanyPicker } from "@/components/supplier-portal/company-switcher";
import { useSupplierSession } from "@/hooks/use-supplier-session";

export default function SelectCompanyPage() {
  const router = useRouter();
  const { principal, isLoading } = useSupplierSession();

  React.useEffect(() => {
    if (!isLoading && !principal) router.replace("/supplier-portal/login");
  }, [isLoading, principal, router]);

  if (isLoading || !principal) return null;

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-5 py-10">
      <CompanyPicker />
    </main>
  );
}
