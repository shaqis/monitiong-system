import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import { getSessionUser } from "@/lib/server-session";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: {
    default: "Uptime Monitor",
    template: "%s | Uptime Monitor",
  },
  description: "Self-hosted URL and web application uptime monitoring dashboard.",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const user = await getSessionUser();

  return (
    <html lang="en">
      <body className="min-h-screen">
        <AuthProvider initialUser={user}>{children}</AuthProvider>
      </body>
    </html>
  );
}
