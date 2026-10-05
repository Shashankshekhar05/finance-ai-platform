"use client";

import Link from "next/link";
import * as React from "react";
import { Badge, Card, CardHeader, KpiSkeleton } from "@/components/display";
import { ChartCard, Kpi, RegionBars, RevenueExpenseChart, type SeriesPoint } from "@/components/finance";
import { useToast } from "@/components/overlay";
import { Button } from "@/components/ui";
import { ApiError } from "@/lib/types";
import {
  fetchConversations,
  fetchDocuments,
  fetchExpenses,
  fetchRevenue,
  fetchTransactions,
  runCalculation,
} from "@/lib/data";
import { formatDate, formatMoney, formatPercent, timeAgo } from "@/lib/format";
import type {
  CalculationResponse,
  ConversationRead,
  DocumentRead,
  TransactionRead,
} from "@/lib/types";

interface KpiState {
  revenue: CalculationResponse | null;
  expenses: CalculationResponse | null;
  margin: CalculationResponse | null;
  loading: boolean;
  mixedCurrency: boolean;
}

function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 7);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(key: string): string {
  const [y, m] = key.split("-").map(Number);
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  if (!y || !m) return key;
  return `${names[m - 1]} ${String(y).slice(2)}`;
}

const SUGGESTIONS = [
  "How did revenue change last year?",
  "Why did expenses increase?",
  "Show revenue by region.",
  "What does the annual report say about revenue?",
];

export default function OverviewPage() {
  const toast = useToast();
  const [kpis, setKpis] = React.useState<KpiState>({ revenue: null, expenses: null, margin: null, loading: true, mixedCurrency: false });
  const [series, setSeries] = React.useState<SeriesPoint[]>([]);
  const [regions, setRegions] = React.useState<{ label: string; value: number }[]>([]);
  const [activity, setActivity] = React.useState<TransactionRead[]>([]);
  const [docs, setDocs] = React.useState<DocumentRead[]>([]);
  const [convos, setConvos] = React.useState<ConversationRead[]>([]);

  React.useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [rev, exp, margin] = await Promise.all([
          runCalculation({ dataset: "revenue", operation: "sum", filters: {} }),
          runCalculation({ dataset: "expense", operation: "sum", filters: {} }),
          runCalculation({ dataset: "revenue", operation: "margin", filters: {} }),
        ]);
        if (!cancelled) setKpis({ revenue: rev, expenses: exp, margin, loading: false, mixedCurrency: false });
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.code === "mixed_currency") {
          setKpis((s) => ({ ...s, loading: false, mixedCurrency: true }));
        } else {
          setKpis((s) => ({ ...s, loading: false }));
          toast.push("error", e instanceof Error ? e.message : "Couldn't load summary figures.");
        }
      }
      try {
        const [revRows, expRows, txns, documents, conversations] = await Promise.all([
          fetchRevenue({ limit: 200, offset: 0, sort: "record_date", order: "asc" }),
          fetchExpenses({ limit: 200, offset: 0, sort: "record_date", order: "asc" }),
          fetchTransactions({ limit: 5, offset: 0, sort: "occurred_at", order: "desc" }),
          fetchDocuments({ limit: 5, offset: 0 }),
          fetchConversations({ limit: 5, offset: 0 }),
        ]);
        if (cancelled) return;
        // Chart grouping is presentational: points aggregate backend rows by month
        // for visualization; every figure shown elsewhere comes from the backend.
        const byMonth = new Map<string, { revenue: number; expenses: number }>();
        for (const r of revRows.items) {
          const k = monthKey(r.record_date);
          const cur = byMonth.get(k) ?? { revenue: 0, expenses: 0 };
          cur.revenue += Number(r.amount);
          byMonth.set(k, cur);
        }
        for (const r of expRows.items) {
          const k = monthKey(r.record_date);
          const cur = byMonth.get(k) ?? { revenue: 0, expenses: 0 };
          cur.expenses += Number(r.amount);
          byMonth.set(k, cur);
        }
        const keys = Array.from(byMonth.keys()).sort().slice(-12);
        setSeries(keys.map((k) => ({ label: monthLabel(k), ...(byMonth.get(k) as { revenue: number; expenses: number }) })));
        const byRegion = new Map<string, number>();
        for (const r of revRows.items) {
          if (!r.region) continue;
          byRegion.set(r.region, (byRegion.get(r.region) ?? 0) + Number(r.amount));
        }
        setRegions(Array.from(byRegion.entries()).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value));
        setActivity(txns.items);
        setDocs(documents.items);
        setConvos(conversations.items);
      } catch (e) {
        if (!cancelled) toast.push("error", e instanceof Error ? e.message : "Couldn't load overview data.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const revSingle = kpis.revenue?.kind === "single" ? kpis.revenue : null;
  const expSingle = kpis.expenses?.kind === "single" ? kpis.expenses : null;
  const margin = kpis.margin?.kind === "margin" ? kpis.margin : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="t-page">Overview</h1>
          <p className="t-meta mt-1">Verified figures from your finance system and documents.</p>
        </div>
        <Link href="/analyst">
          <Button variant="secondary">Ask the AI Analyst →</Button>
        </Link>
      </div>

      {kpis.mixedCurrency ? (
        <div role="alert" className="rounded-[var(--radius-md)] border border-[var(--warning)] bg-[var(--warning-wash)] px-4 py-3 text-[13.5px]">
          Records span multiple currencies, so totals can&apos;t be combined. Filter by currency on the detail pages.
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-live="polite">
        {kpis.loading ? (
          <>
            <KpiSkeleton />
            <KpiSkeleton />
            <KpiSkeleton />
            <KpiSkeleton />
          </>
        ) : (
          <>
            <Kpi
              label="Total revenue"
              value={revSingle && revSingle.has_data ? formatMoney(revSingle.value, revSingle.currency) : "—"}
              sub={revSingle ? `${revSingle.record_count} records` : "No data yet"}
            />
            <Kpi
              label="Total expenses"
              value={expSingle && expSingle.has_data ? formatMoney(expSingle.value, expSingle.currency) : "—"}
              sub={expSingle ? `${expSingle.record_count} records` : "No data yet"}
            />
            <Kpi
              label="Net position"
              value={margin && margin.has_data ? formatMoney(margin.absolute_value, margin.currency) : "—"}
              sub="Revenue minus expenses"
              tone={margin && margin.absolute_value !== null ? (Number(margin.absolute_value) >= 0 ? "positive" : "negative") : "default"}
            />
            <Kpi
              label="Net margin"
              value={margin && margin.has_data ? formatPercent(margin.margin_percent) : "—"}
              sub="Share of revenue retained"
            />
          </>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ChartCard title="Revenue vs expenses" subtitle="Monthly totals from recorded rows">
            <div className="py-2">
              <RevenueExpenseChart data={series} />
            </div>
          </ChartCard>
        </div>
        <ChartCard title="Revenue by region" subtitle="Top regions by recorded revenue">
          <RegionBars data={regions} />
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Ask the analyst" subtitle="Grounded in verified evidence" />
          <ul className="flex flex-col gap-2 p-5 pt-4">
            {SUGGESTIONS.map((s) => (
              <li key={s}>
                <Link
                  href={`/analyst?q=${encodeURIComponent(s)}`}
                  className="block rounded-[var(--radius-md)] border border-[var(--line)] px-3.5 py-2.5 text-[13.5px] transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-wash)]"
                >
                  {s}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title="Recent activity" subtitle="Latest transactions" action={<Link href="/transactions" className="t-meta font-semibold text-[var(--accent-deep)] hover:underline">View all</Link>} />
          {activity.length === 0 ? (
            <p className="t-meta px-5 py-6 text-center">No transactions recorded yet.</p>
          ) : (
            <ul className="divide-y divide-[var(--line-soft)]">
              {activity.map((t) => (
                <li key={t.id} className="flex items-baseline justify-between gap-3 px-5 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-[13.5px] font-medium">{t.description ?? t.category ?? t.account ?? "Transaction"}</p>
                    <p className="t-meta">{formatDate(t.occurred_at)} · {t.type}</p>
                  </div>
                  <span className={`t-table num shrink-0 font-semibold ${t.type === "income" ? "text-[var(--positive)]" : t.type === "expense" ? "text-[var(--negative)]" : ""}`}>
                    {formatMoney(t.amount, t.currency)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader title="Recent documents" action={<Link href="/documents" className="t-meta font-semibold text-[var(--accent-deep)] hover:underline">View all</Link>} />
            {docs.length === 0 ? (
              <p className="t-meta px-5 py-6 text-center">No documents uploaded yet.</p>
            ) : (
              <ul className="divide-y divide-[var(--line-soft)]">
                {docs.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-[13.5px] font-medium">{d.title}</p>
                      <p className="t-meta">{formatDate(d.created_at)}{d.page_count ? ` · ${d.page_count} pages` : ""}</p>
                    </div>
                    <Badge tone={d.status === "indexed" ? "positive" : d.status === "failed" ? "negative" : "warning"}>{d.status}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Recent conversations" action={<Link href="/conversations" className="t-meta font-semibold text-[var(--accent-deep)] hover:underline">View all</Link>} />
            {convos.length === 0 ? (
              <p className="t-meta px-5 py-6 text-center">No conversations yet. <Link href="/analyst" className="font-semibold text-[var(--accent-deep)] hover:underline">Start one</Link>.</p>
            ) : (
              <ul className="divide-y divide-[var(--line-soft)]">
                {convos.map((c) => (
                  <li key={c.id} className="px-5 py-2.5">
                    <Link href={`/analyst?c=${c.id}`} className="block truncate text-[13.5px] font-medium hover:underline">
                      {c.title ?? "Untitled conversation"}
                    </Link>
                    <p className="t-meta">{c.message_count} messages · {timeAgo(c.updated_at)}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

    </div>
  );
}
