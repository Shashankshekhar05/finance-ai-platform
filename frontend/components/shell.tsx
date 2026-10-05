"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";
import { AuthProvider, canWrite, useAuth } from "@/lib/auth-store";
import { ToastProvider } from "./overlay";

const NAV = [
  { href: "/overview", label: "Overview" },
  { href: "/analyst", label: "AI Analyst" },
  { href: "/revenue", label: "Revenue" },
  { href: "/expenses", label: "Expenses" },
  { href: "/transactions", label: "Transactions" },
  { href: "/documents", label: "Documents" },
  { href: "/conversations", label: "Conversations" },
  { href: "/settings", label: "Settings" },
] as const;

function Guard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, loading } = useAuth();

  React.useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading) {
    return (
      <div className="flex min-h-screen overflow-x-clip">
        <div className="hidden w-60 shrink-0 border-r border-[var(--line)] bg-[var(--surface)] p-4 md:block">
          <div className="skeleton h-6 w-32" />
          <div className="mt-6 flex flex-col gap-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="skeleton h-9 w-full" />
            ))}
          </div>
        </div>
        <div className="flex-1 p-6">
          <div className="skeleton h-8 w-56" />
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <div className="skeleton h-28" />
            <div className="skeleton h-28" />
            <div className="skeleton h-28" />
          </div>
        </div>
      </div>
    );
  }
  if (!user) return null;
  return <>{children}</>;
}

function ShellBody({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { companyName, role, logout } = useAuth();
  const router = useRouter();

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen overflow-x-clip">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-[var(--line)] bg-[var(--surface)] md:flex">
        <div className="border-b border-[var(--line-soft)] px-5 py-4">
          <p className="t-app">LedgerLens</p>
          {companyName ? <p className="t-meta mt-0.5 truncate">{companyName}</p> : null}
        </div>
        <nav aria-label="Primary" className="flex-1 overflow-y-auto p-3">
          <ul className="flex flex-col gap-0.5">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex items-center rounded-[var(--radius-md)] px-3 py-2 text-[14px] transition-colors ${
                      active
                        ? "bg-[var(--accent-wash)] font-semibold text-[var(--accent-deep)]"
                        : "text-[var(--muted)] hover:bg-[var(--paper)] hover:text-[var(--ink)]"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="border-t border-[var(--line-soft)] p-3">
          {role ? (
            <p className="t-meta px-3 pb-2 capitalize">
              Signed in · {role}
              {!canWrite(role) ? " · read-only" : ""}
            </p>
          ) : null}
          <button
            onClick={handleLogout}
            className="flex w-full items-center rounded-[var(--radius-md)] px-3 py-2 text-left text-[14px] text-[var(--muted)] transition-colors hover:bg-[var(--paper)] hover:text-[var(--ink)]"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-10 border-b border-[var(--line)] bg-[var(--surface)] md:hidden">
          <div className="flex items-center justify-between px-4 py-2.5">
            <p className="t-app text-[15px]">LedgerLens</p>
            <button
              onClick={handleLogout}
              className="rounded-[var(--radius-sm)] px-2 py-1 text-[13px] font-medium text-[var(--muted)] hover:text-[var(--ink)]"
            >
              Sign out
            </button>
          </div>
          <nav aria-label="Primary" className="overflow-x-auto px-2 pb-2">
            <ul className="flex gap-1">
              {NAV.map((item) => {
                const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                return (
                  <li key={item.href} className="shrink-0">
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={`block rounded-full px-3 py-1.5 text-[13px] transition-colors ${
                        active
                          ? "bg-[var(--accent-wash)] font-semibold text-[var(--accent-deep)]"
                          : "text-[var(--muted)] hover:text-[var(--ink)]"
                      }`}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <ToastProvider>
        <Guard>
          <ShellBody>{children}</ShellBody>
        </Guard>
      </ToastProvider>
    </AuthProvider>
  );
}
