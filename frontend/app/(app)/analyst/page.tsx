"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { ChatComposer, ChatMessage, TypingPlaceholder } from "@/components/chat";
import { InsufficientEvidence } from "@/components/citations";
import { Button } from "@/components/ui";
import { apiRequest } from "@/lib/api";
import { fetchConversations } from "@/lib/data";
import { timeAgo } from "@/lib/format";
import type { AnswerResponse, ConversationDetailRead, ConversationRead } from "@/lib/types";

interface Bubble {
  key: string;
  role: "user" | "assistant";
  content: string;
  answer?: AnswerResponse | null;
}

const SUGGESTIONS = [
  "How did revenue change last year?",
  "Why did expenses increase?",
  "Show revenue by region.",
  "What does the annual report say about revenue?",
];

export default function AnalystPage() {
  return (
    <React.Suspense fallback={<p className="t-meta" role="status">Loading analyst…</p>}>
      <AnalystInner />
    </React.Suspense>
  );
}

function AnalystInner() {
  const search = useSearchParams();
  const router = useRouter();
  const [threads, setThreads] = React.useState<ConversationRead[]>([]);
  const [threadsLoading, setThreadsLoading] = React.useState(true);
  const [conversationId, setConversationId] = React.useState<string | null>(null);
  const [bubbles, setBubbles] = React.useState<Bubble[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [lastQuestion, setLastQuestion] = React.useState<string | null>(null);
  const autoSent = React.useRef<string | null>(null);
  const listRef = React.useRef<HTMLDivElement>(null);
  const bottomRef = React.useRef<HTMLDivElement>(null);

  const refreshThreads = React.useCallback(async () => {
    try {
      const page = await fetchConversations({ limit: 50, offset: 0 });
      setThreads(page.items);
    } catch {
      /* sidebar stays empty; main surface reports errors */
    } finally {
      setThreadsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  React.useEffect(() => {
    // Container-scoped auto-scroll only. Never use sentinel.scrollIntoView()
    // here: it scrolls every ancestor including the window, which shifts the
    // static app sidebar partially off-screen (horizontal page scroll).
    const el = listRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [bubbles, loading]);

  const loadConversation = React.useCallback(async (id: string) => {
    setConversationId(id);
    setError(null);
    setBubbles([]);
    try {
      const detail = await apiRequest<ConversationDetailRead>(`/conversations/${id}`);
      setBubbles(
        detail.messages.map((m) => ({
          key: m.id,
          role: m.role === "assistant" ? "assistant" : "user",
          content: m.content,
        })),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load this conversation.");
    }
  }, []);

  async function send(question: string) {
    const q = question.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    setLastQuestion(q);
    const userKey = `u-${Date.now()}`;
    setBubbles((prev) => [...prev, { key: userKey, role: "user", content: q }]);
    try {
      let cid = conversationId;
      if (!cid) {
        const created = await apiRequest<ConversationRead>("/conversations", {
          method: "POST",
          body: { title: q.slice(0, 80) },
        });
        cid = created.id;
        setConversationId(cid);
        void refreshThreads();
      }
      const answer = await apiRequest<AnswerResponse>("/ai/query", {
        method: "POST",
        body: { question: q, conversation_id: cid },
      });
      setBubbles((prev) => [
        ...prev,
        { key: `a-${Date.now()}`, role: "assistant", content: answer.answer, answer },
      ]);
      void refreshThreads();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "The analyst couldn't answer. Please try again.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  function retry() {
    if (lastQuestion) {
      setError(null);
      // Drop the failed user bubble's orphan state by resending fresh.
      setBubbles((prev) => (prev.length > 0 && prev[prev.length - 1].role === "user" ? prev.slice(0, -1) : prev));
      void send(lastQuestion);
    }
  }

  function startNew() {
    setConversationId(null);
    setBubbles([]);
    setError(null);
    setLastQuestion(null);
    router.replace("/analyst");
  }

  // Deep links: /analyst?c=<id> loads history, /analyst?q=<prompt> asks it.
  React.useEffect(() => {
    const c = search.get("c");
    const q = search.get("q");
    if (c && c !== conversationId && !loading) {
      void loadConversation(c);
    } else if (q && autoSent.current !== q && !loading) {
      autoSent.current = q;
      startNew();
      void send(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div>
        <h1 className="t-page">AI Analyst</h1>
        <p className="t-meta mt-1">Ask questions about your company&apos;s finances — every figure is cited.</p>
      </div>

      <div className="grid min-w-0 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* Conversation sidebar */}
        <aside aria-label="Conversations" className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--line)] bg-[var(--surface)] p-3 shadow-[var(--shadow-card)]">
          <Button variant="secondary" size="sm" className="w-full" onClick={startNew}>
            + New conversation
          </Button>
          <div className="mt-3">
            {threadsLoading ? (
              <div className="flex flex-col gap-2" role="status" aria-label="Loading conversations">
                <div className="skeleton h-11 w-full" />
                <div className="skeleton h-11 w-full" />
                <div className="skeleton h-11 w-full" />
              </div>
            ) : threads.length === 0 ? (
              <p className="t-meta px-1 py-3 text-center">No conversations yet.</p>
            ) : (
              <ul className="flex max-h-96 flex-col gap-1 overflow-y-auto">
                {threads.map((t) => {
                  const active = t.id === conversationId;
                  return (
                    <li key={t.id}>
                      <button
                        onClick={() => {
                          router.replace(`/analyst?c=${t.id}`);
                          void loadConversation(t.id);
                        }}
                        aria-current={active ? "true" : undefined}
                        className={`block w-full rounded-[var(--radius-md)] px-3 py-2 text-left transition-colors ${
                          active ? "bg-[var(--accent-wash)]" : "hover:bg-[var(--paper)]"
                        }`}
                      >
                        <span className={`block truncate text-[13.5px] ${active ? "font-semibold text-[var(--accent-deep)]" : "font-medium"}`}>
                          {t.title ?? "Untitled conversation"}
                        </span>
                        <span className="t-meta">{t.message_count} messages · {timeAgo(t.updated_at)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </aside>

        {/* Main conversation */}
        <section aria-label="Analyst conversation" className="flex min-h-[540px] min-w-0 flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--line)] bg-[var(--paper)] shadow-[var(--shadow-card)]">
          <div ref={listRef} className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto overflow-x-hidden px-4 py-5 md:px-6">
            {bubbles.length === 0 && !loading ? (
              <div className="m-auto flex w-full max-w-lg flex-col items-center gap-2 py-10 text-center">
                <div aria-hidden="true" className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--accent-wash)]">
                  <span className="text-[22px] text-[var(--accent-deep)]">✦</span>
                </div>
                <h2 className="t-section text-[17px]">What should we look at first?</h2>
                <p className="t-meta max-w-md">
                  Answers come from your recorded figures and uploaded documents, with citations you can inspect.
                </p>
                <div className="mt-3 grid w-full gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => void send(s)}
                      className="rounded-[var(--radius-md)] border border-[var(--line)] bg-[var(--surface)] px-3.5 py-2.5 text-left text-[13.5px] transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-wash)]"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              bubbles.map((b) => <ChatMessage key={b.key} role={b.role} content={b.content} answer={b.answer} />)
            )}
            {loading ? <TypingPlaceholder /> : null}
            {error ? (
              <div role="alert" className="flex items-start justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--negative)] bg-[var(--surface)] px-4 py-3">
                <div>
                  <p className="text-[14px] font-semibold text-[var(--negative)]">The analyst ran into a problem</p>
                  <p className="t-meta mt-0.5">{error}</p>
                  {error.toLowerCase().includes("permission") ? (
                    <p className="t-meta mt-1 font-semibold text-[var(--negative)]">Permission denied</p>
                  ) : null}
                  {error.toLowerCase().includes("enough verified") ? <InsufficientEvidence /> : null}
                </div>
                <Button variant="secondary" size="sm" onClick={retry}>
                  Retry
                </Button>
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>
          <ChatComposer loading={loading} onSend={(t) => void send(t)} />
        </section>
      </div>

      <p className="t-meta">
        Prefer a list view? <Link href="/conversations" className="font-semibold text-[var(--accent-deep)] hover:underline">Browse all conversations</Link>.
      </p>
    </div>
  );
}
