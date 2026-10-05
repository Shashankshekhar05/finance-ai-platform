/* Typed models mirroring backend Pydantic DTOs. Backend is authoritative;
   the frontend never invents values of these shapes. Amounts arrive as
   exact decimal strings (never floats). */

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string;
  };
}

export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

/* ------- Auth ------- */

export interface CompanyMembership {
  company_id: string;
  company_name: string;
  role: "viewer" | "analyst" | "admin";
}

export interface UserRead {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  companies: CompanyMembership[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

/* ------- Finance rows ------- */

export interface RevenueRead {
  id: string;
  company_id: string;
  amount: string;
  currency: string;
  record_date: string;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  segment: string | null;
  region: string | null;
  category: string | null;
  source_document_id: string | null;
  source_page: number | null;
  created_at: string;
  updated_at: string;
}

export interface ExpenseRead {
  id: string;
  company_id: string;
  amount: string;
  currency: string;
  record_date: string;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  category: string | null;
  department: string | null;
  vendor: string | null;
  region: string | null;
  source_document_id: string | null;
  source_page: number | null;
  created_at: string;
  updated_at: string;
}

export interface TransactionRead {
  id: string;
  company_id: string;
  amount: string;
  currency: string;
  type: "income" | "expense" | "transfer";
  occurred_at: string;
  account: string | null;
  category: string | null;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface MetricRead {
  id: string;
  company_id: string;
  metric_name: string;
  period: string;
  value: string;
  unit: string | null;
  computed_by: string;
  created_at: string;
  updated_at: string;
}

/* ------- Documents ------- */

export type DocumentStatus = "uploaded" | "processing" | "indexed" | "failed";

export interface DocumentRead {
  id: string;
  company_id: string;
  title: string;
  original_filename: string;
  media_type: string;
  file_size: number;
  sha256_hash: string;
  fiscal_year: number | null;
  status: string;
  page_count: number | null;
  ingestion_error: string | null;
  ingestion_error_code: string | null;
  embedding_status: string;
  embedding_model: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface UploadResponse {
  document: DocumentRead;
  duplicate: boolean;
}

export interface PageRead {
  id: string;
  document_id: string;
  company_id: string;
  page_number: number;
  page_type: string;
  extracted_text: string;
  extraction_status: string;
  extraction_error: string | null;
  text_char_count: number;
  has_tables: boolean;
  has_images: boolean;
  table_count: number;
  tables: Array<Record<string, unknown>> | null;
  created_at: string;
  updated_at: string;
}

/* ------- Calculations (deterministic backend results) ------- */

export type CalculationKind = "single" | "grouped" | "comparison" | "margin";

export interface CalculationProvenance {
  dataset: string;
  operation: string;
  filters: Record<string, unknown>;
  group_by: string[];
  company_id: string;
  record_count: number;
  source_type: string;
  calculated_at: string;
}

export interface SingleResult {
  kind: "single";
  dataset: string;
  operation: string;
  value: string | null;
  unit: string;
  currency: string | null;
  has_data: boolean;
  record_count: number;
  status: string;
  provenance: CalculationProvenance;
}

export interface GroupValue {
  dimensions: Record<string, string | null>;
  value: string | null;
  record_count: number;
  has_data: boolean;
}

export interface GroupedResult {
  kind: "grouped";
  dataset: string;
  operation: string;
  unit: string;
  currency: string | null;
  groups: GroupValue[];
  record_count: number;
  status: string;
  provenance: CalculationProvenance;
}

export interface ComparisonResult {
  kind: "comparison";
  dataset: string;
  operation: string;
  current_value: string | null;
  comparison_value: string | null;
  absolute_variance: string | null;
  percent_value: string | null;
  unit: string;
  currency: string | null;
  has_data: boolean;
  record_count: number;
  status: string;
  reason: string | null;
  current_period: { fiscal_year: number; quarter: number | null } | null;
  comparison_period: { fiscal_year: number; quarter: number | null } | null;
  provenance: CalculationProvenance;
}

export interface MarginResult {
  kind: "margin";
  operation: string;
  revenue_value: string | null;
  expense_value: string | null;
  absolute_value: string | null;
  margin_percent: string | null;
  unit: string;
  currency: string | null;
  has_data: boolean;
  record_count: number;
  status: string;
  reason: string | null;
  provenance: CalculationProvenance;
}

export type CalculationResponse = SingleResult | GroupedResult | ComparisonResult | MarginResult;

/* ------- AI answers (evidence-grounded, backend-orchestrated) ------- */

export type AnswerStatus = "grounded" | "insufficient_evidence" | "citation_invalid";

export interface Citation {
  evidence_id: string;
  source_type: string;
  document_title: string | null;
  page_number: number | null;
  chunk_id: string | null;
  dataset: string | null;
  operation: string | null;
}

export interface AnswerResponse {
  status: AnswerStatus;
  answer: string;
  citations: Citation[];
}

/* ------- Conversations ------- */

export interface ConversationRead {
  id: string;
  company_id: string;
  user_id: string;
  title: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface MessageRead {
  id: string;
  role: string;
  content: string;
  sequence: number;
  created_at: string;
}

export interface ConversationDetailRead extends ConversationRead {
  messages: MessageRead[];
}
