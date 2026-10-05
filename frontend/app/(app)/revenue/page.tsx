"use client";

import * as React from "react";
import { Card } from "@/components/display";
import { Modal, useToast } from "@/components/overlay";
import { DataTable, Pagination, type Column } from "@/components/table";
import { Button, Field, Input, Select } from "@/components/ui";
import { apiRequest } from "@/lib/api";
import { canWrite, isAdmin, useAuth } from "@/lib/auth-store";
import { usePage } from "@/lib/data";
import { formatDate, formatMoney } from "@/lib/format";
import type { RevenueRead } from "@/lib/types";

const COLUMNS: Column<RevenueRead>[] = [
  { key: "date", header: "Date", render: (r) => formatDate(r.record_date) },
  { key: "amount", header: "Amount", numeric: true, render: (r) => <span className="num font-semibold">{formatMoney(r.amount, r.currency)}</span> },
  { key: "region", header: "Region", render: (r) => r.region ?? "—" },
  { key: "segment", header: "Segment", render: (r) => r.segment ?? "—" },
  { key: "category", header: "Category", render: (r) => r.category ?? "—" },
  {
    key: "period",
    header: "Period",
    render: (r) => (r.fiscal_year ? `FY${r.fiscal_year}${r.fiscal_quarter ? ` Q${r.fiscal_quarter}` : ""}` : "—"),
  },
];

function CreateRevenue({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const [amount, setAmount] = React.useState("");
  const [currency, setCurrency] = React.useState("INR");
  const [date, setDate] = React.useState("");
  const [region, setRegion] = React.useState("");
  const [segment, setSegment] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await apiRequest("/revenue", {
        method: "POST",
        body: {
          amount: Number(amount),
          currency,
          record_date: date,
          region: region || null,
          segment: segment || null,
          category: category || null,
        },
      });
      toast.push("success", "Revenue record created.");
      onCreated();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Couldn't create the record.";
      setError(msg);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Add revenue" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3.5">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount">
            <Input type="number" min="0" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="4200.00" />
          </Field>
          <Field label="Currency">
            <Input required value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={3} />
          </Field>
        </div>
        <Field label="Record date">
          <Input type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Region">
            <Input value={region} onChange={(e) => setRegion(e.target.value)} maxLength={100} />
          </Field>
          <Field label="Segment">
            <Input value={segment} onChange={(e) => setSegment(e.target.value)} maxLength={100} />
          </Field>
          <Field label="Category">
            <Input value={category} onChange={(e) => setCategory(e.target.value)} maxLength={100} />
          </Field>
        </div>
        {error ? <p role="alert" className="text-[13px] font-medium text-[var(--negative)]">{error}</p> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Save record"}</Button>
        </div>
      </form>
    </Modal>
  );
}

export default function RevenuePage() {
  const { role } = useAuth();
  const toast = useToast();
  const [offset, setOffset] = React.useState(0);
  const [sort, setSort] = React.useState("record_date");
  const [order, setOrder] = React.useState("desc");
  const [region, setRegion] = React.useState("");
  const [fiscalYear, setFiscalYear] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  const limit = 25;
  const { data, loading, error, reload } = usePage<RevenueRead>("/revenue", {
    limit,
    offset,
    sort,
    order,
    region: region || undefined,
    fiscal_year: fiscalYear ? Number(fiscalYear) : undefined,
  });

  async function remove(id: string) {
    if (!window.confirm("Delete this revenue record? This can't be undone.")) return;
    try {
      await apiRequest(`/revenue/${id}`, { method: "DELETE" });
      toast.push("success", "Record deleted.");
      reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Couldn't delete the record.");
    }
  }

  const columns: Column<RevenueRead>[] = isAdmin(role)
    ? [
        ...COLUMNS,
        {
          key: "actions",
          header: "Actions",
          render: (r) => (
            <button onClick={() => void remove(r.id)} className="font-medium text-[var(--negative)] hover:underline" aria-label={`Delete revenue record ${r.id}`}>
              Delete
            </button>
          ),
        },
      ]
    : COLUMNS;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="t-page">Revenue</h1>
          <p className="t-meta mt-1">{data ? `${data.total} records` : "Recorded revenue"} · figures from the backend</p>
        </div>
        {canWrite(role) ? <Button onClick={() => setCreating(true)}>Add revenue</Button> : null}
      </div>

      <Card>
        <form
          className="flex flex-wrap items-end gap-3 border-b border-[var(--line-soft)] px-5 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            setOffset(0);
            reload();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rev-region" className="t-label">Region</label>
            <Input id="rev-region" value={region} onChange={(e) => setRegion(e.target.value)} placeholder="All regions" className="h-9 w-40" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rev-fy" className="t-label">Fiscal year</label>
            <Input id="rev-fy" type="number" value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value)} placeholder="2025" className="h-9 w-28" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rev-sort" className="t-label">Sort</label>
            <Select id="rev-sort" value={sort} onChange={(e) => setSort(e.target.value)} className="h-9">
              <option value="record_date">Date</option>
              <option value="amount">Amount</option>
              <option value="created_at">Created</option>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rev-order" className="t-label">Order</label>
            <Select id="rev-order" value={order} onChange={(e) => setOrder(e.target.value)} className="h-9">
              <option value="desc">Newest first</option>
              <option value="asc">Oldest first</option>
            </Select>
          </div>
          <Button type="submit" variant="secondary" size="sm">Apply</Button>
        </form>
        <DataTable
          caption="Revenue records"
          columns={columns}
          rows={data?.items ?? []}
          loading={loading}
          error={error}
          onRetry={reload}
          emptyTitle="No revenue records"
          emptyDescription="No revenue matches these filters. Adjust the filters or add a record."
        />
        {data && data.total > 0 ? (
          <Pagination total={data.total} limit={limit} offset={offset} onChange={setOffset} />
        ) : null}
      </Card>
      {creating ? <CreateRevenue onClose={() => setCreating(false)} onCreated={reload} /> : null}
    </div>
  );
}
