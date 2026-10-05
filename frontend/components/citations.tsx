"use client";

import * as React from "react";
import type { Citation } from "@/lib/types";

/** Clickable citation chip + expandable evidence. Renders only backend citations. */
export function CitationChip({ citation }: { citation: Citation }) {
  const [open, setOpen] = React.useState(false);
  const isCalc = citation.source_type === "calculation" || citation.dataset !== null;
  const label = citation.evidence_id;
  return (
    <span className="inline-flex flex-col">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={isCalc ? "Show calculation source" : "Show document source"}
        className={`inline-flex h-6 items-center rounded-full px-2.5 text-[11.5px] font-bold tracking-wide transition-colors ${
          isCalc
            ? "bg-[var(--accent-wash)] text-[var(--accent-deep)] hover:bg-[#d4e6e1]"
            : "bg-[var(--surface-warm)] text-[var(--ink)] hover:bg-[#ece4d0]"
        }`}
      >
        {label}
      </button>
      {open ? (
        <span className="pop-in mt-1.5 block w-72 whitespace-normal rounded-[var(--radius-md)] border border-[var(--line)] bg-[var(--surface)] p-3 text-left shadow-[var(--shadow-pop)]">
          {isCalc ? (
            <>
              <span className="t-label block">Calculation</span>
              <span className="mt-1 block text-[13px]">
                {citation.operation ? <strong>{citation.operation}</strong> : "Computed value"}
                {citation.dataset ? ` · ${citation.dataset}` : ""}
              </span>
              <span className="t-meta mt-1 block">Verified by the deterministic calculation engine.</span>
            </>
          ) : (
            <>
              <span className="t-label block">Document</span>
              <span className="mt-1 block text-[13px] font-semibold">
                {citation.document_title ?? "Untitled document"}
                {citation.page_number ? ` · Page ${citation.page_number}` : ""}
              </span>
              <span className="t-meta mt-1 block">
                Source: {citation.source_type}
                {citation.chunk_id ? ` · excerpt ${citation.chunk_id.slice(0, 8)}` : ""}
              </span>
            </>
          )}
        </span>
      ) : null}
    </span>
  );
}

export function CitationRow({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-label="Citations">
      {citations.map((c) => (
        <CitationChip key={c.evidence_id} citation={c} />
      ))}
    </div>
  );
}

export function InsufficientEvidence() {
  return (
    <div className="mt-2 rounded-[var(--radius-md)] border border-[var(--warning)] bg-[var(--warning-wash)] px-3.5 py-2.5 text-[13.5px]">
      <strong className="text-[var(--warning)]">Insufficient evidence.</strong>{" "}
      <span className="text-[var(--ink)]">
        I don&apos;t have enough verified information to answer that. Try asking about revenue,
        expenses, or an uploaded document.
      </span>
    </div>
  );
}
