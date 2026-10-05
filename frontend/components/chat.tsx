"use client";

import * as React from "react";
import { CitationRow, InsufficientEvidence } from "./citations";
import type { AnswerResponse } from "@/lib/types";

/** Assistant answer with structured evidence. Backend text is authoritative. */
export function ChatMessage({
  role,
  content,
  answer,
}: {
  role: "user" | "assistant";
  content: string;
  answer?: AnswerResponse | null;
}) {
  if (role === "user") {
    return (
      <div className="flex min-w-0 justify-end">
        <div className="min-w-0 max-w-[85%] break-words rounded-[var(--radius-lg)] rounded-br-[var(--radius-sm)] bg-[var(--ink)] px-4 py-2.5 text-[14px] leading-relaxed text-[var(--paper)]">
          {content}
        </div>
      </div>
    );
  }
  return (
    <div className="rise-in flex min-w-0 justify-start">
      <div className="min-w-0 max-w-[92%] break-words rounded-[var(--radius-lg)] rounded-bl-[var(--radius-sm)] border border-[var(--line)] bg-[var(--surface)] px-4 py-3 shadow-[var(--shadow-card)]">
        <p className="text-[13.5px] font-semibold text-[var(--accent-deep)]">Analyst</p>
        <div className="mt-1 whitespace-pre-wrap break-words text-[14px] leading-relaxed">{content}</div>
        {answer ? (
          <>
            <CitationRow citations={answer.citations} />
            {answer.status === "insufficient_evidence" ? <InsufficientEvidence /> : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

export function TypingPlaceholder() {
  return (
    <div className="flex justify-start" role="status" aria-label="Waiting for analyst response">
      <div className="flex flex-col gap-2 rounded-[var(--radius-lg)] rounded-bl-[var(--radius-sm)] border border-[var(--line)] bg-[var(--surface)] px-4 py-3">
        <div className="skeleton h-3.5 w-56" />
        <div className="skeleton h-3.5 w-40" />
      </div>
    </div>
  );
}

const MAX_LEN = 2000;

export function ChatComposer({
  loading,
  onSend,
}: {
  loading: boolean;
  onSend: (text: string) => void;
}) {
  const [value, setValue] = React.useState("");
  const trimmed = value.trim();
  const disabled = loading || trimmed.length === 0 || value.length > MAX_LEN;

  function submit() {
    if (disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <div className="border-t border-[var(--line)] bg-[var(--surface)] px-4 py-3">
      <div className="flex items-end gap-2">
        <label htmlFor="composer" className="sr-only">
          Ask about your company&apos;s finances
        </label>
        <textarea
          id="composer"
          rows={2}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Ask about revenue, expenses, or your documents…"
          maxLength={MAX_LEN + 100}
          disabled={loading}
          className="max-h-36 min-h-[52px] flex-1 resize-y rounded-[var(--radius-md)] border border-[var(--line)] bg-[var(--paper)] px-3 py-2.5 text-[14px] placeholder:text-[var(--faint)] focus:border-[var(--accent)] focus:outline-none disabled:opacity-60"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled}
          aria-label="Send question"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--accent-ink)] transition-colors hover:bg-[var(--accent-deep)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          <span aria-hidden="true">↑</span>
        </button>
      </div>
      <div className="mt-1.5 flex items-center justify-between">
        <p className="t-meta">Enter to send · Shift+Enter for a new line</p>
        <p className={`t-meta num ${value.length > MAX_LEN ? "font-semibold text-[var(--negative)]" : ""}`}>
          {value.length}/{MAX_LEN}
        </p>
      </div>
    </div>
  );
}
