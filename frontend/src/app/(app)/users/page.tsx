import { redirect } from "next/navigation";
import { UsersView } from "@/components/users/users-view";
import { listUsers } from "@/lib/api";
import { getCookieHeader, getRequiredUser } from "@/lib/server-session";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Users",
};

export default async function UsersPage() {
  const user = await getRequiredUser();
  if (user.role !== "admin") {
    redirect("/dashboard");
  }

  const users = await listUsers({ cookieHeader: getCookieHeader() });

  return <UsersView initialUsers={users} currentUser={user} />;
}
