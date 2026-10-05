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
import type { ExpenseRead } from "@/lib/types";

const COLUMNS: Column<ExpenseRead>[] = [
  { key: "date", header: "Date", render: (r) => formatDate(r.record_date) },
  { key: "amount", header: "Amount", numeric: true, render: (r) => <span className="num font-semibold">{formatMoney(r.amount, r.currency)}</span> },
  { key: "category", header: "Category", render: (r) => r.category ?? "—" },
  { key: "department", header: "Department", render: (r) => r.department ?? "—" },
  { key: "vendor", header: "Vendor", render: (r) => r.vendor ?? "—" },
  {
    key: "period",
    header: "Period",
    render: (r) => (r.fiscal_year ? `FY${r.fiscal_year}${r.fiscal_quarter ? ` Q${r.fiscal_quarter}` : ""}` : "—"),
  },
];

function CreateExpense({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const [amount, setAmount] = React.useState("");
  const [currency, setCurrency] = React.useState("INR");
  const [date, setDate] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [department, setDepartment] = React.useState("");
  const [vendor, setVendor] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await apiRequest("/expenses", {
        method: "POST",
        body: {
          amount: Number(amount),
          currency,
          record_date: date,
          category: category || null,
          department: department || null,
          vendor: vendor || null,
        },
      });
      toast.push("success", "Expense record created.");
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create the record.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Add expense" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3.5">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount">
            <Input type="number" min="0" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="1200.00" />
          </Field>
          <Field label="Currency">
            <Input required value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={3} />
          </Field>
        </div>
        <Field label="Record date">
          <Input type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Category">
            <Input value={category} onChange={(e) => setCategory(e.target.value)} maxLength={100} />
          </Field>
          <Field label="Department">
            <Input value={department} onChange={(e) => setDepartment(e.target.value)} maxLength={100} />
          </Field>
          <Field label="Vendor">
            <Input value={vendor} onChange={(e) => setVendor(e.target.value)} maxLength={200} />
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

export default function ExpensesPage() {
  const { role } = useAuth();
  const toast = useToast();
  const [offset, setOffset] = React.useState(0);
  const [sort, setSort] = React.useState("record_date");
  const [order, setOrder] = React.useState("desc");
  const [category, setCategory] = React.useState("");
  const [fiscalYear, setFiscalYear] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  const limit = 25;
  const { data, loading, error, reload } = usePage<ExpenseRead>("/expenses", {
    limit,
    offset,
    sort,
    order,
    category: category || undefined,
    fiscal_year: fiscalYear ? Number(fiscalYear) : undefined,
  });

  async function remove(id: string) {
    if (!window.confirm("Delete this expense record? This can't be undone.")) return;
    try {
      await apiRequest(`/expenses/${id}`, { method: "DELETE" });
      toast.push("success", "Record deleted.");
      reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Couldn't delete the record.");
    }
  }

  const columns: Column<ExpenseRead>[] = isAdmin(role)
    ? [
        ...COLUMNS,
        {
          key: "actions",
          header: "Actions",
          render: (r) => (
            <button onClick={() => void remove(r.id)} className="font-medium text-[var(--negative)] hover:underline" aria-label={`Delete expense record ${r.id}`}>
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
          <h1 className="t-page">Expenses</h1>
          <p className="t-meta mt-1">{data ? `${data.total} records` : "Recorded expenses"} · figures from the backend</p>
        </div>
        {canWrite(role) ? <Button onClick={() => setCreating(true)}>Add expense</Button> : null}
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
            <label htmlFor="exp-cat" className="t-label">Category</label>
            <Input id="exp-cat" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="All categories" className="h-9 w-44" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="exp-fy" className="t-label">Fiscal year</label>
            <Input id="exp-fy" type="number" value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value)} placeholder="2025" className="h-9 w-28" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="exp-sort" className="t-label">Sort</label>
            <Select id="exp-sort" value={sort} onChange={(e) => setSort(e.target.value)} className="h-9">
              <option value="record_date">Date</option>
              <option value="amount">Amount</option>
              <option value="created_at">Created</option>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="exp-order" className="t-label">Order</label>
            <Select id="exp-order" value={order} onChange={(e) => setOrder(e.target.value)} className="h-9">
              <option value="desc">Newest first</option>
              <option value="asc">Oldest first</option>
            </Select>
          </div>
          <Button type="submit" variant="secondary" size="sm">Apply</Button>
        </form>
        <DataTable
          caption="Expense records"
          columns={columns}
          rows={data?.items ?? []}
          loading={loading}
          error={error}
          onRetry={reload}
          emptyTitle="No expense records"
          emptyDescription="No expenses match these filters. Adjust the filters or add a record."
        />
        {data && data.total > 0 ? <Pagination total={data.total} limit={limit} offset={offset} onChange={setOffset} /> : null}
      </Card>
      {creating ? <CreateExpense onClose={() => setCreating(false)} onCreated={reload} /> : null}
    </div>
  );
}
