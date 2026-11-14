"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, LogOut } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";
import type { User } from "@/types";

const MOBILE_ITEMS = [
  { href: "/dashboard", label: "Dashboard", adminOnly: false },
  { href: "/urls", label: "URLs", adminOnly: false },
  { href: "/users", label: "Users", adminOnly: true },
];

function pageTitle(pathname: string): string {
  if (pathname.startsWith("/urls/")) {
    return "URL details";
  }
  if (pathname === "/urls") {
    return "URLs";
  }
  if (pathname === "/users") {
    return "Users";
  }
  if (pathname === "/dashboard") {
    return "Dashboard";
  }
  return "Uptime Monitor";
}

interface TopbarProps {
  user: User;
  isAdmin: boolean;
}

export function Topbar({ user, isAdmin }: TopbarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { logout } = useAuth();
  const [pending, setPending] = useState(false);

  async function handleLogout() {
    setPending(true);
    try {
      await logout();
      router.refresh();
    } finally {
      setPending(false);
    }
  }

  return (
    <header className="sticky top-0 z-30 border-b bg-white/95 backdrop-blur">
      <div className="flex h-16 items-center justify-between gap-4 px-4 lg:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/dashboard" className="flex items-center gap-2 lg:hidden">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Activity className="h-4 w-4" aria-hidden="true" />
            </span>
            <span className="sr-only">Uptime Monitor</span>
          </Link>
          <h1 className="truncate text-base font-semibold tracking-tight">{pageTitle(pathname)}</h1>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-2 sm:flex">
            <span className="max-w-[12rem] truncate text-sm text-muted-foreground">
              {user.full_name}
            </span>
            <Badge variant={isAdmin ? "default" : "secondary"} className="uppercase">
              {user.role}
            </Badge>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleLogout}
            disabled={pending}
          >
            <LogOut aria-hidden="true" />
            <span className="hidden sm:inline">{pending ? "Signing out…" : "Sign out"}</span>
          </Button>
        </div>
      </div>

      <nav className="flex gap-1 overflow-x-auto border-t px-2 py-1 lg:hidden" aria-label="Mobile navigation">
        {MOBILE_ITEMS.filter((item) => !item.adminOnly || isAdmin).map((item) => {
          const active =
            item.href === "/urls" ? pathname.startsWith("/urls") : pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                active ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted",
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
