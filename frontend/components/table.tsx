"use client";

import * as React from "react";
import { Button } from "./ui";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
      <div aria-hidden="true" className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-[var(--surface-warm)]">
        <span className="text-[20px] text-[var(--faint)]">○</span>
      </div>
      <h3 className="t-section">{title}</h3>
      <p className="t-meta max-w-sm">{description}</p>
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title,
  description,
  onRetry,
}: {
  title: string;
  description: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-14 text-center" role="alert">
      <div aria-hidden="true" className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-[var(--negative-wash)]">
        <span className="text-[20px] text-[var(--negative)]">!</span>
      </div>
      <h3 className="t-section">{title}</h3>
      <p className="t-meta max-w-sm">{description}</p>
      {onRetry ? (
        <div className="mt-3">
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(total, offset + limit);
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 border-t border-[var(--line-soft)] px-5 py-3">
      <p className="t-meta" aria-live="polite">
        {from}–{to} of {total}
      </p>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onChange(offset - limit)} aria-label="Previous page">
          ←
        </Button>
        <span className="t-meta num" aria-current="page">
          {page} / {pages}
        </span>
        <Button
          variant="secondary"
          size="sm"
          disabled={page >= pages}
          onClick={() => onChange(offset + limit)}
          aria-label="Next page"
        >
          →
        </Button>
      </div>
    </nav>
  );
}

export interface Column<T> {
  key: string;
  header: string;
  numeric?: boolean;
  render: (row: T) => React.ReactNode;
}

export function DataTable<T extends { id: string }>({
  columns,
  rows,
  loading,
  error,
  emptyTitle,
  emptyDescription,
  onRetry,
  caption,
}: {
  columns: Column<T>[];
  rows: T[];
  loading: boolean;
  error: string | null;
  emptyTitle: string;
  emptyDescription: string;
  onRetry?: () => void;
  caption: string;
}) {
  if (loading) {
    return (
      <div role="status" aria-label={`Loading ${caption}`} className="flex flex-col gap-2 p-5">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} aria-hidden="true" className="skeleton h-9 w-full rounded-[var(--radius-sm)]" />
        ))}
      </div>
    );
  }
  if (error) {
    return <ErrorState title={`Couldn't load ${caption.toLowerCase()}`} description={error} onRetry={onRetry} />;
  }
  if (rows.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-[var(--line)]">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`t-label sticky top-0 bg-[var(--surface)] px-4 py-2.5 font-semibold ${c.numeric ? "text-right" : "text-left"}`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} tabIndex={0} className="border-b border-[var(--line-soft)] transition-colors last:border-0 hover:bg-[var(--paper)] focus:bg-[var(--paper)]">
              {columns.map((c) => (
                <td key={c.key} className={`t-table px-4 py-2.5 ${c.numeric ? "text-right" : ""}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
