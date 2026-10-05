"use client";

import Link from "next/link";
import * as React from "react";
import { Card } from "@/components/display";
import { useToast } from "@/components/overlay";
import { DataTable, Pagination } from "@/components/table";
import { Button } from "@/components/ui";
import { apiRequest } from "@/lib/api";
import { usePage } from "@/lib/data";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { ConversationRead } from "@/lib/types";

export default function ConversationsPage() {
  const toast = useToast();
  const [offset, setOffset] = React.useState(0);
  const limit = 25;
  const { data, loading, error, reload } = usePage<ConversationRead>("/conversations", { limit, offset });

  async function remove(id: string) {
    if (!window.confirm("Delete this conversation and its messages?")) return;
    try {
      await apiRequest(`/conversations/${id}`, { method: "DELETE" });
      toast.push("success", "Conversation deleted.");
      reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Couldn't delete the conversation.");
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="t-page">Conversations</h1>
          <p className="t-meta mt-1">{data ? `${data.total} threads` : "Your analyst threads"}</p>
        </div>
        <Link href="/analyst">
          <Button>New conversation</Button>
        </Link>
      </div>
      <Card>
        <DataTable
          caption="Conversations"
          columns={[
            {
              key: "title",
              header: "Title",
              render: (c: ConversationRead) => (
                <Link href={`/analyst?c=${c.id}`} className="font-medium text-[var(--accent-deep)] hover:underline">
                  {c.title ?? "Untitled conversation"}
                </Link>
              ),
            },
            { key: "messages", header: "Messages", numeric: true, render: (c: ConversationRead) => <span className="num">{c.message_count}</span> },
            { key: "updated", header: "Updated", render: (c: ConversationRead) => `${timeAgo(c.updated_at)} · ${formatDateTime(c.updated_at)}` },
            {
              key: "actions",
              header: "Actions",
              render: (c: ConversationRead) => (
                <button onClick={() => void remove(c.id)} className="font-medium text-[var(--negative)] hover:underline" aria-label={`Delete conversation ${c.title ?? c.id}`}>
                  Delete
                </button>
              ),
            },
          ]}
          rows={data?.items ?? []}
          loading={loading}
          error={error}
          onRetry={reload}
          emptyTitle="No conversations yet"
          emptyDescription="Ask the AI Analyst a question to start your first thread."
        />
        {data && data.total > 0 ? <Pagination total={data.total} limit={limit} offset={offset} onChange={setOffset} /> : null}
      </Card>
    </div>
  );
}
