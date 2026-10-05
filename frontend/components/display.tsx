"use client";

import * as React from "react";

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return (
    <section className={`rounded-[var(--radius-lg)] border border-[var(--line)] bg-[var(--surface)] shadow-[var(--shadow-card)] ${className}`}>
      {children}
    </section>
  );
}

export function CardHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--line-soft)] px-5 py-4">
      <div className="min-w-0">
        <h2 className="t-section">{title}</h2>
        {subtitle ? <p className="t-meta mt-0.5">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

const BADGE_STYLES: Record<string, string> = {
  default: "bg-[var(--surface-warm)] text-[var(--muted)]",
  accent: "bg-[var(--accent-wash)] text-[var(--accent-deep)]",
  positive: "bg-[var(--positive-wash)] text-[var(--positive)]",
  negative: "bg-[var(--negative-wash)] text-[var(--negative)]",
  warning: "bg-[var(--warning-wash)] text-[var(--warning)]",
};

export function Badge({ tone = "default", children }: { tone?: keyof typeof BADGE_STYLES; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex h-6 items-center rounded-full px-2.5 text-[12px] font-semibold ${BADGE_STYLES[tone]}`}
    >
      {children}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`skeleton rounded-[var(--radius-sm)] ${className}`} />;
}

export function KpiSkeleton() {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--line)] bg-[var(--surface)] p-5">
      <Skeleton className="h-3.5 w-24" />
      <Skeleton className="mt-3 h-8 w-36" />
      <Skeleton className="mt-2 h-3 w-28" />
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div aria-label="Loading table" role="status" className="flex flex-col gap-2 p-5">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}
