"use client";

import * as React from "react";
import { Badge, Card } from "@/components/display";
import { Modal, useToast } from "@/components/overlay";
import { DataTable, Pagination } from "@/components/table";
import { Button, Field, Input, Select } from "@/components/ui";
import { apiRequest } from "@/lib/api";
import { canWrite, useAuth } from "@/lib/auth-store";
import { usePage } from "@/lib/data";
import { formatBytes, formatDate } from "@/lib/format";
import type { DocumentRead, PageRead, UploadResponse } from "@/lib/types";

function DocumentDetail({ doc, onClose }: { doc: DocumentRead; onClose: () => void }) {
  const [pages, setPages] = React.useState<PageRead[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    apiRequest<PageRead[]>(`/documents/${doc.id}/pages`)
      .then((p) => {
        if (!cancelled) setPages(p);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Couldn't load pages.");
      });
    return () => {
      cancelled = true;
    };
  }, [doc.id]);

  return (
    <Modal title={doc.title} onClose={onClose}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13.5px]">
        <dt className="t-label">File</dt>
        <dd className="truncate">{doc.original_filename}</dd>
        <dt className="t-label">Status</dt>
        <dd>{doc.status} · embeddings {doc.embedding_status}</dd>
        <dt className="t-label">Pages / chunks</dt>
        <dd className="num">{doc.page_count ?? "—"} / {doc.chunk_count}</dd>
        <dt className="t-label">Size</dt>
        <dd className="num">{formatBytes(doc.file_size)}</dd>
        {doc.ingestion_error ? (
          <>
            <dt className="t-label">Error</dt>
            <dd className="text-[var(--negative)]">{doc.ingestion_error}</dd>
          </>
        ) : null}
      </dl>
      <h3 className="t-section mt-4">Pages</h3>
      {error ? (
        <p role="alert" className="mt-2 text-[13px] text-[var(--negative)]">{error}</p>
      ) : pages === null ? (
        <div className="mt-2 flex flex-col gap-2" role="status" aria-label="Loading pages">
          <div className="skeleton h-12 w-full" />
          <div className="skeleton h-12 w-full" />
        </div>
      ) : pages.length === 0 ? (
        <p className="t-meta mt-2">No extracted pages yet.</p>
      ) : (
        <ul className="mt-2 flex max-h-72 flex-col gap-2 overflow-y-auto">
          {pages.map((p) => (
            <li key={p.id} className="rounded-[var(--radius-md)] border border-[var(--line-soft)] p-3">
              <p className="t-label">Page {p.page_number} · {p.page_type}</p>
              <p className="mt-1 line-clamp-3 text-[13px] text-[var(--muted)]">
                {p.extracted_text ? p.extracted_text.slice(0, 280) : "No text extracted."}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}

function UploadCard({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [title, setTitle] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [dragOver, setDragOver] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  function pick(f: File | null) {
    setError(null);
    if (!f) {
      setFile(null);
      return;
    }
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF documents are accepted.");
      return;
    }
    setFile(f);
    if (!title) setTitle(f.name.replace(/\.pdf$/i, ""));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !title.trim()) {
      setError("Choose a PDF file and give it a title.");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("title", title.trim());
      const res = await apiRequest<UploadResponse>("/documents/upload", { method: "POST", form });
      toast.push("success", res.duplicate ? "This file already exists — opened the existing document." : "Document uploaded and indexed.");
      setFile(null);
      setTitle("");
      onDone();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed.";
      setError(msg);
    } finally {
      setUploading(false);
    }
  }

  return (
    <Card>
      <form
        onSubmit={submit}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          pick(e.dataTransfer.files?.[0] ?? null);
        }}
        className={`flex flex-col gap-3.5 rounded-[var(--radius-lg)] p-5 transition-colors ${dragOver ? "bg-[var(--accent-wash)]" : ""}`}
      >
        <div>
          <h2 className="t-section">Upload a document</h2>
          <p className="t-meta mt-0.5">PDF only. Drag and drop or browse. Duplicates are detected automatically.</p>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          aria-label="Choose a PDF file"
          className={`rounded-[var(--radius-md)] border border-dashed px-4 py-6 text-center transition-colors ${dragOver ? "border-[var(--accent)]" : "border-[var(--line)] hover:border-[var(--faint)]"}`}
        >
          <span className="text-[14px] font-medium">{file ? file.name : "Drop a PDF here, or click to browse"}</span>
          <span className="t-meta mt-1 block">{file ? `${formatBytes(file.size)} · click to replace` : "Annual reports, filings, statements"}</span>
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="sr-only"
          aria-hidden="false"
          tabIndex={-1}
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />
        <Field label="Title">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="FY2025 Annual Report" maxLength={255} />
        </Field>
        {error ? <p role="alert" className="text-[13px] font-medium text-[var(--negative)]">{error}</p> : null}
        <div>
          <Button type="submit" disabled={uploading || !file}>
            {uploading ? "Uploading…" : "Upload and index"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

export default function DocumentsPage() {
  const { role } = useAuth();
  const toast = useToast();
  const [offset, setOffset] = React.useState(0);
  const [status, setStatus] = React.useState("");
  const [selected, setSelected] = React.useState<DocumentRead | null>(null);

  const limit = 25;
  const { data, loading, error, reload } = usePage<DocumentRead>("/documents", {
    limit,
    offset,
    status: status || undefined,
  });

  async function reprocess(id: string) {
    try {
      await apiRequest(`/documents/${id}/reprocess`, { method: "POST" });
      toast.push("success", "Reprocessing started.");
      reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Couldn't reprocess the document.");
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="t-page">Documents</h1>
        <p className="t-meta mt-1">{data ? `${data.total} documents` : "Uploaded financial documents"} · indexed for grounded answers</p>
      </div>
      {canWrite(role) ? <UploadCard onDone={() => { setOffset(0); reload(); }} /> : null}
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
            <label htmlFor="doc-status" className="t-label">Status</label>
            <Select id="doc-status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-9">
              <option value="">All statuses</option>
              <option value="uploaded">Uploaded</option>
              <option value="processing">Processing</option>
              <option value="indexed">Indexed</option>
              <option value="failed">Failed</option>
            </Select>
          </div>
          <Button type="submit" variant="secondary" size="sm">Apply</Button>
        </form>
        <DataTable
          caption="Documents"
          columns={[
            {
              key: "title",
              header: "Title",
              render: (d: DocumentRead) => (
                <button onClick={() => setSelected(d)} className="max-w-[260px] truncate text-left font-medium text-[var(--accent-deep)] hover:underline">
                  {d.title}
                </button>
              ),
            },
            { key: "date", header: "Uploaded", render: (d: DocumentRead) => formatDate(d.created_at) },
            { key: "pages", header: "Pages", numeric: true, render: (d: DocumentRead) => <span className="num">{d.page_count ?? "—"}</span> },
            { key: "chunks", header: "Chunks", numeric: true, render: (d: DocumentRead) => <span className="num">{d.chunk_count}</span> },
            {
              key: "status",
              header: "Status",
              render: (d: DocumentRead) => (
                <span className="flex flex-col items-start gap-1">
                  <Badge tone={d.status === "indexed" ? "positive" : d.status === "failed" ? "negative" : "warning"}>{d.status}</Badge>
                  <span className="t-meta">embeddings: {d.embedding_status}</span>
                </span>
              ),
            },
            {
              key: "actions",
              header: "Actions",
              render: (d: DocumentRead) =>
                d.status === "failed" && canWrite(role) ? (
                  <button onClick={() => void reprocess(d.id)} className="font-medium text-[var(--accent-deep)] hover:underline">
                    Retry
                  </button>
                ) : (
                  <span className="t-meta">—</span>
                ),
            },
          ]}
          rows={data?.items ?? []}
          loading={loading}
          error={error}
          onRetry={reload}
          emptyTitle="No documents"
          emptyDescription={canWrite(role) ? "Upload your first PDF above to enable document-grounded answers." : "No documents have been uploaded yet."}
        />
        {data && data.total > 0 ? <Pagination total={data.total} limit={limit} offset={offset} onChange={setOffset} /> : null}
      </Card>
      {selected ? <DocumentDetail doc={selected} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}
