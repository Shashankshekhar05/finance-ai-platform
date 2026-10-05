/* Centralized typed API client. All backend traffic goes through here —
   components never call fetch() directly. Same-origin /api/* prefix hits the
   Next.js rewrite proxy, so no CORS change is needed on the backend. */

import { ApiError, type ApiErrorEnvelope } from "./types";
import { clearToken, getToken } from "./auth-store";

const API_PREFIX = "/api";

const FRIENDLY_BY_CODE: Record<string, string> = {
  authentication_required: "Please sign in to continue.",
  invalid_token: "Your session is no longer valid. Please sign in again.",
  token_expired: "Your session has expired. Please sign in again.",
  inactive_user: "This account is no longer active.",
  insufficient_permissions: "You don't have permission to perform this action.",
  tenant_mismatch: "The requested company does not match your membership.",
  not_found: "The requested resource was not found.",
  validation_error: "Please check the highlighted fields.",
  file_too_large: "The uploaded file exceeds the maximum allowed size.",
  too_many_pages: "The PDF exceeds the maximum page count.",
  corrupt_document: "The uploaded file is not a readable PDF.",
  invalid_state: "The requested action is not valid for the current state.",
  unsupported_calculation: "The requested calculation is not supported.",
  llm_unavailable: "The AI service is temporarily unavailable. Please try again later.",
  llm_error: "The AI service returned an error. Please try again.",
  internal_error: "Something went wrong on our side. Please try again.",
};

const FRIENDLY_BY_STATUS: Record<number, string> = {
  401: "Please sign in to continue.",
  403: "You don't have permission to perform this action.",
  404: "The requested resource was not found.",
  409: "This conflicts with an existing record.",
  422: "Please check the highlighted fields.",
  502: "The finance service is temporarily unavailable. Please try again.",
  503: "The finance service is temporarily unavailable. Please try again.",
};

function friendlyMessage(status: number, code: string, fallback: string): string {
  if (FRIENDLY_BY_CODE[code]) return FRIENDLY_BY_CODE[code];
  if (FRIENDLY_BY_STATUS[status]) return FRIENDLY_BY_STATUS[status];
  return fallback || "Something went wrong. Please try again.";
}

function isEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const err = (value as Record<string, unknown>)["error"];
  if (typeof err !== "object" || err === null) return false;
  const rec = err as Record<string, unknown>;
  return typeof rec["code"] === "string" && typeof rec["message"] === "string";
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form !== undefined) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`${API_PREFIX}${path}`, {
      method: opts.method ?? "GET",
      headers,
      body,
      signal: opts.signal,
    });
  } catch {
    throw new ApiError(0, "network_unavailable", "Unable to connect to the finance service.");
  }

  if (res.status === 204) return undefined as T;

  if (res.status === 401) {
    // Expired/invalid session: drop the stored token so the shell redirects.
    clearToken();
  }

  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  if (!res.ok) {
    if (isEnvelope(parsed)) {
      throw new ApiError(
        res.status,
        parsed.error.code,
        friendlyMessage(res.status, parsed.error.code, parsed.error.message),
        typeof parsed.error.request_id === "string" ? parsed.error.request_id : undefined,
      );
    }
    throw new ApiError(res.status, `http_${res.status}`, friendlyMessage(res.status, "", ""));
  }
  return (parsed as T) ?? (undefined as T);
}

export function apiQuery(path: string, params: Record<string, string | number | undefined | null>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const suffix = qs.toString();
  return suffix ? `${path}?${suffix}` : path;
}
