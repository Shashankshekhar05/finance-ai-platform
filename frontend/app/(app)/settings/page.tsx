"use client";

import { useRouter } from "next/navigation";
import { Badge, Card, CardHeader } from "@/components/display";
import { Button } from "@/components/ui";
import { canWrite, isAdmin, useAuth } from "@/lib/auth-store";
import { formatDate } from "@/lib/format";

export default function SettingsPage() {
  const { user, loading, role, logout } = useAuth();
  const router = useRouter();

  if (loading) {
    return (
      <div className="flex flex-col gap-2" role="status" aria-label="Loading settings">
        <div className="skeleton h-8 w-48" />
        <div className="skeleton h-40 w-full" />
      </div>
    );
  }

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <div>
        <h1 className="t-page">Settings</h1>
        <p className="t-meta mt-1">Your profile and workspace access. Roles are enforced by the backend.</p>
      </div>
      <Card>
        <CardHeader title="Profile" />
        <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2.5 px-5 py-4 text-[14px]">
          <dt className="t-label">Name</dt>
          <dd>{user?.full_name ?? "—"}</dd>
          <dt className="t-label">Email</dt>
          <dd>{user?.email ?? "—"}</dd>
          <dt className="t-label">Member since</dt>
          <dd>{formatDate(user?.created_at ?? null)}</dd>
          <dt className="t-label">Status</dt>
          <dd>{user?.is_active ? <Badge tone="positive">active</Badge> : <Badge tone="negative">inactive</Badge>}</dd>
        </dl>
      </Card>
      <Card>
        <CardHeader title="Companies & roles" subtitle="UI gating only — the backend re-validates every request" />
        <ul className="divide-y divide-[var(--line-soft)]">
          {(user?.companies ?? []).map((m) => (
            <li key={m.company_id} className="flex items-center justify-between gap-3 px-5 py-3">
              <span className="text-[14px] font-medium">{m.company_name}</span>
              <Badge tone={m.role === "admin" ? "accent" : m.role === "analyst" ? "default" : "default"}>{m.role}</Badge>
            </li>
          ))}
          {(user?.companies ?? []).length === 0 ? (
            <li className="px-5 py-4"><p className="t-meta">No company memberships.</p></li>
          ) : null}
        </ul>
        <div className="border-t border-[var(--line-soft)] px-5 py-4">
          <p className="t-meta">
            {role === "admin" && "As an admin you can manage records, including deletes."}
            {role === "analyst" && "As an analyst you can create records and upload documents."}
            {role === "viewer" && "As a viewer you have read access plus AI queries."}
            {!canWrite(role) && !isAdmin(role) && role !== "viewer" ? "Your role couldn't be determined." : ""}
          </p>
          {!canWrite(role) ? <p className="t-meta mt-1">Write actions are hidden because your role is read-only.</p> : null}
        </div>
      </Card>
      <div>
        <Button variant="secondary" onClick={handleLogout}>
          Sign out
        </Button>
      </div>
    </div>
  );
}
