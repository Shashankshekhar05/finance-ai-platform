"use client";

import * as React from "react";
import { Badge, Card } from "@/components/display";
import { useToast } from "@/components/overlay";
import { DataTable, Pagination, type Column } from "@/components/table";
import { Button, Input, Select } from "@/components/ui";
import { apiRequest } from "@/lib/api";
import { isAdmin, useAuth } from "@/lib/auth-store";
import { usePage } from "@/lib/data";
import { formatDateTime, formatMoney } from "@/lib/format";
import type { TransactionRead } from "@/lib/types";

const COLUMNS: Column<TransactionRead>[] = [
  { key: "when", header: "Occurred", render: (r) => formatDateTime(r.occurred_at) },
  {
    key: "type",
    header: "Type",
    render: (r) => (
      <Badge tone={r.type === "income" ? "positive" : r.type === "expense" ? "negative" : "default"}>{r.type}</Badge>
    ),
  },
  { key: "amount", header: "Amount", numeric: true, render: (r) => <span className="num font-semibold">{formatMoney(r.amount, r.currency)}</span> },
  { key: "account", header: "Account", render: (r) => r.account ?? "—" },
  { key: "category", header: "Category", render: (r) => r.category ?? "—" },
  { key: "desc", header: "Description", render: (r) => <span className="block max-w-[220px] truncate">{r.description ?? "—"}</span> },
];

export default function TransactionsPage() {
  const { role } = useAuth();
  const toast = useToast();
  const [offset, setOffset] = React.useState(0);
  const [type, setType] = React.useState("");
  const [account, setAccount] = React.useState("");

  const limit = 25;
  const { data, loading, error, reload } = usePage<TransactionRead>("/transactions", {
    limit,
    offset,
    sort: "occurred_at",
    order: "desc",
    type: type || undefined,
    account: account || undefined,
  });

  async function remove(id: string) {
    if (!window.confirm("Delete this transaction? This can't be undone.")) return;
    try {
      await apiRequest(`/transactions/${id}`, { method: "DELETE" });
      toast.push("success", "Transaction deleted.");
      reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Couldn't delete the transaction.");
    }
  }

  const columns: Column<TransactionRead>[] = isAdmin(role)
    ? [
        ...COLUMNS,
        {
          key: "actions",
          header: "Actions",
          render: (r) => (
            <button onClick={() => void remove(r.id)} className="font-medium text-[var(--negative)] hover:underline" aria-label={`Delete transaction ${r.id}`}>
              Delete
            </button>
          ),
        },
      ]
    : COLUMNS;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="t-page">Transactions</h1>
        <p className="t-meta mt-1">{data ? `${data.total} records` : "Recorded transactions"} · figures from the backend</p>
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
            <label htmlFor="txn-type" className="t-label">Type</label>
            <Select id="txn-type" value={type} onChange={(e) => setType(e.target.value)} className="h-9">
              <option value="">All types</option>
              <option value="income">Income</option>
              <option value="expense">Expense</option>
              <option value="transfer">Transfer</option>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="txn-acct" className="t-label">Account</label>
            <Input id="txn-acct" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="All accounts" className="h-9 w-44" />
          </div>
          <Button type="submit" variant="secondary" size="sm">Apply</Button>
        </form>
        <DataTable
          caption="Transaction records"
          columns={columns}
          rows={data?.items ?? []}
          loading={loading}
          error={error}
          onRetry={reload}
          emptyTitle="No transactions"
          emptyDescription="No transactions match these filters."
        />
        {data && data.total > 0 ? <Pagination total={data.total} limit={limit} offset={offset} onChange={setOffset} /> : null}
      </Card>
    </div>
  );
}
