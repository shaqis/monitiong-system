import { redirect } from "next/navigation";
import { ApiError, getCurrentUser } from "@/lib/api";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { getCookieHeader, getRequiredUser } from "@/lib/server-session";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const cookieHeader = getCookieHeader();
  if (!cookieHeader) {
    redirect("/login");
  }

  let user;
  try {
    user = await getRequiredUser();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      redirect("/login");
    }
    throw error;
  }

  const isAdmin = user.role === "admin";

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <Sidebar isAdmin={isAdmin} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar user={user} isAdmin={isAdmin} />
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 lg:px-8 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
