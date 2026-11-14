import { MonitorsView } from "@/components/monitors/monitors-view";
import { listMonitors } from "@/lib/api";
import { normalizeStatusFilter } from "@/lib/params";
import { getCookieHeader, getRequiredUser } from "@/lib/server-session";
import { firstParam } from "@/lib/utils";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "URLs",
};

interface UrlsPageProps {
  searchParams: { q?: string | string[]; status?: string | string[] };
}

export default async function UrlsPage({ searchParams }: UrlsPageProps) {
  const user = await getRequiredUser();
  const search = (firstParam(searchParams.q) ?? "").trim();
  const status = normalizeStatusFilter(firstParam(searchParams.status));

  const monitors = await listMonitors(
    { search: search || undefined, status },
    { cookieHeader: getCookieHeader() },
  );

  return (
    <MonitorsView
      monitors={monitors}
      isAdmin={user.role === "admin"}
      initialSearch={search}
      initialStatus={status}
    />
  );
}
