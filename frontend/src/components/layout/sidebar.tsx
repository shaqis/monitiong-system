"use client";

import type { ComponentType } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Link2, LayoutDashboard, Users } from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  adminOnly?: boolean;
  matches: (pathname: string) => boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    matches: (pathname) => pathname === "/dashboard",
  },
  {
    href: "/urls",
    label: "URLs",
    icon: Link2,
    matches: (pathname) => pathname === "/urls" || pathname.startsWith("/urls/"),
  },
  {
    href: "/users",
    label: "Users",
    icon: Users,
    adminOnly: true,
    matches: (pathname) => pathname === "/users",
  },
];

interface SidebarProps {
  isAdmin: boolean;
}

export function Sidebar({ isAdmin }: SidebarProps) {
  const pathname = usePathname();
  const items = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);

  return (
    <aside className="hidden w-64 shrink-0 border-r bg-white lg:flex lg:flex-col">
      <div className="flex h-16 items-center gap-2 border-b px-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Activity className="h-4 w-4" aria-hidden="true" />
        </div>
        <span className="text-sm font-semibold tracking-tight">Uptime Monitor</span>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3" aria-label="Main navigation">
        {items.map((item) => {
          const Icon = item.icon;
          const active = item.matches(pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t px-6 py-4 text-xs text-muted-foreground">
        {isAdmin ? "Administrator access" : "Read-only access"}
      </div>
    </aside>
  );
}

export { NAV_ITEMS };
