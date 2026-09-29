import type { Metadata } from "next";

import { ProfileScreen } from "@/components/profile/profile-screen";

export const metadata: Metadata = {
  title: "My Profile",
  description: "Your personal details, access and password.",
};

export default function ProfilePage() {
  return <ProfileScreen />;
}
