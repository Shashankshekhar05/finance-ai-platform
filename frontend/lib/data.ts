"use client";

/* Data-access helpers: thin typed wrappers over the centralized apiRequest.
   Backend remains authoritative — no financial math happens here. */

import * as React from "react";
import { apiQuery, apiRequest } from "./api";
import type {
  CalculationResponse,
  DocumentRead,
  ExpenseRead,
  MetricRead,
  Page,
  RevenueRead,
  TransactionRead,
  ConversationRead,
} from "./types";

export interface Paging {
  limit: number;
  offset: number;
}

export function usePage<T>(
  path: string | null,
  params: Record<string, string | number | undefined | null> & Paging,
) {
  const [data, setData] = React.useState<Page<T> | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [nonce, setNonce] = React.useState(0);
  const key = React.useMemo(() => (path ? apiQuery(path, params) : null), [path, params]);

  React.useEffect(() => {
    if (!key) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiRequest<Page<T>>(key)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Unable to load data.");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, nonce]);

  const reload = React.useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload };
}

export async function fetchRevenue(params: Record<string, string | number | undefined | null>) {
  return apiRequest<Page<RevenueRead>>(apiQuery("/revenue", params));
}

export async function fetchExpenses(params: Record<string, string | number | undefined | null>) {
  return apiRequest<Page<ExpenseRead>>(apiQuery("/expenses", params));
}

export async function fetchTransactions(params: Record<string, string | number | undefined | null>) {
  return apiRequest<Page<TransactionRead>>(apiQuery("/transactions", params));
}

export async function fetchMetrics(params: Record<string, string | number | undefined | null>) {
  return apiRequest<Page<MetricRead>>(apiQuery("/financial-metrics", params));
}

export async function fetchDocuments(params: Record<string, string | number | undefined | null>) {
  return apiRequest<Page<DocumentRead>>(apiQuery("/documents", params));
}

export async function fetchConversations(params: Record<string, string | number | undefined | null>) {
  return apiRequest<Page<ConversationRead>>(apiQuery("/conversations", params));
}

/** Deterministic backend calculation — the authoritative figure source for KPIs. */
export async function runCalculation(body: Record<string, unknown>): Promise<CalculationResponse> {
  return apiRequest<CalculationResponse>("/calculations", { method: "POST", body });
}
