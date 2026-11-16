import { redirect } from "next/navigation";
import { NotificationSettingsView } from "@/components/settings/notification-settings-view";
import { getNotificationSettings } from "@/lib/api";
import { getCookieHeader, getRequiredUser } from "@/lib/server-session";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Settings",
};

export default async function SettingsPage() {
  const user = await getRequiredUser();
  if (user.role !== "admin") {
    redirect("/dashboard");
  }

  const settings = await getNotificationSettings({ cookieHeader: getCookieHeader() });

  return <NotificationSettingsView settings={settings} />;
}
