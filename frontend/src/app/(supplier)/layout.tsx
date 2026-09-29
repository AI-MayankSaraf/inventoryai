import { SupplierSessionProvider } from "@/hooks/use-supplier-session";

export default function SupplierPortalLayout({ children }: { children: React.ReactNode }) {
  return <SupplierSessionProvider>{children}</SupplierSessionProvider>;
}
