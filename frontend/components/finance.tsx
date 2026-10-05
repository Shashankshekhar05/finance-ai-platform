"use client";

import * as React from "react";
import { Card } from "./display";

/* KPI card — renders backend-verified figures only. */

export function Kpi({
  label,
  value,
  sub,
  tone = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "positive" | "negative";
}) {
  const valueColor =
    tone === "positive"
      ? "text-[var(--positive)]"
      : tone === "negative"
        ? "text-[var(--negative)]"
        : "";
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--line)] bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]">
      <p className="t-label">{label}</p>
      <p className={`t-kpi num mt-1.5 ${valueColor}`}>{value}</p>
      {sub ? <p className="t-meta mt-1">{sub}</p> : null}
    </div>
  );
}

/* ------- Minimal dependency-free SVG charts (backend data only) ------- */

export interface SeriesPoint {
  label: string;
  revenue: number;
  expenses: number;
}

const CHART = { w: 640, h: 220, padL: 8, padR: 8, padT: 12, padB: 26 };

export function RevenueExpenseChart({ data }: { data: SeriesPoint[] }) {
  if (data.length === 0) {
    return <p className="t-meta px-5 py-8 text-center">No data in this period yet.</p>;
  }
  const max = Math.max(1, ...data.map((d) => Math.max(d.revenue, d.expenses)));
  const iw = CHART.w - CHART.padL - CHART.padR;
  const ih = CHART.h - CHART.padT - CHART.padB;
  const x = (i: number) => CHART.padL + (data.length === 1 ? iw / 2 : (i / (data.length - 1)) * iw);
  const y = (v: number) => CHART.padT + ih - (v / max) * ih;
  const line = (pick: (d: SeriesPoint) => number) =>
    data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(pick(d)).toFixed(1)}`).join(" ");
  const ticks = data.length <= 8 ? data : data.filter((_, i) => i % Math.ceil(data.length / 8) === 0);

  return (
    <figure role="img" aria-label={`Revenue versus expenses across ${data.length} periods`}>
      <svg viewBox={`0 0 ${CHART.w} ${CHART.h}`} className="h-auto w-full">
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line
            key={f}
            x1={CHART.padL}
            x2={CHART.w - CHART.padR}
            y1={CHART.padT + ih - f * ih}
            y2={CHART.padT + ih - f * ih}
            stroke="var(--line-soft)"
            strokeWidth={1}
          />
        ))}
        <path d={line((d) => d.revenue)} fill="none" stroke="var(--accent)" strokeWidth={2.5} strokeLinejoin="round" />
        <path d={line((d) => d.expenses)} fill="none" stroke="var(--negative)" strokeWidth={2} strokeDasharray="5 4" strokeLinejoin="round" />
        {data.map((d, i) => (
          <g key={i}>
            <circle cx={x(i)} cy={y(d.revenue)} r={3.5} fill="var(--accent)">
              <title>{`${d.label} revenue: ${d.revenue.toFixed(2)}`}</title>
            </circle>
            <circle cx={x(i)} cy={y(d.expenses)} r={3} fill="var(--surface)" stroke="var(--negative)" strokeWidth={2}>
              <title>{`${d.label} expenses: ${d.expenses.toFixed(2)}`}</title>
            </circle>
          </g>
        ))}
        {ticks.map((d) => {
          const i = data.indexOf(d);
          return (
            <text key={d.label} x={x(i)} y={CHART.h - 8} textAnchor="middle" fontSize={11} fill="var(--muted)">
              {d.label}
            </text>
          );
        })}
      </svg>
      <figcaption className="flex items-center gap-4 px-5 pb-4 pt-1">
        <span className="t-meta flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-0.5 w-5 bg-[var(--accent)]" /> Revenue
        </span>
        <span className="t-meta flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-0 w-5 border-t-2 border-dashed border-[var(--negative)]" /> Expenses
        </span>
      </figcaption>
    </figure>
  );
}

export function RegionBars({ data }: { data: { label: string; value: number }[] }) {
  if (data.length === 0) {
    return <p className="t-meta px-5 py-8 text-center">No regional breakdown available.</p>;
  }
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <ul className="flex flex-col gap-3 px-5 py-4" role="img" aria-label="Revenue by region">
      {data.slice(0, 8).map((d) => (
        <li key={d.label}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-[13.5px] font-medium">{d.label}</span>
            <span className="t-table num text-[var(--muted)]">{d.value.toFixed(2)}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-[var(--surface-warm)]">
            <div
              className="h-full rounded-full bg-[var(--accent)]"
              style={{ width: `${Math.max(2, (d.value / max) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <Card>
      <div className="border-b border-[var(--line-soft)] px-5 py-4">
        <h2 className="t-section">{title}</h2>
        {subtitle ? <p className="t-meta mt-0.5">{subtitle}</p> : null}
      </div>
      {children}
    </Card>
  );
}
