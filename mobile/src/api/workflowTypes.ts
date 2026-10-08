/** گردش کار موبایل (R297): کارتابل یکپارچه و جزئیات کار. */

export interface WorkInboxItem {
  key: string;
  source: string; // WF | CARTABLE | DOC | CRM
  source_label: string;
  kind: string;
  kind_label: string;
  ref_id: number;
  title: string;
  subtitle: string;
  due_at: string | null;
  is_overdue: boolean;
  priority_code: string;
  priority_label: string;
  created_at: string | null;
  can_decide: boolean;
  status_note: string;
  definition: string | null;
}

export interface WorkInboxResponse {
  items: WorkInboxItem[];
  count: number;
  overdue: number;
}

export interface WorkTaskDetail {
  task_id: number;
  title: string;
  kind: string;
  kind_label: string;
  instructions: string;
  definition: string;
  entity_label: string;
  requested_by: string;
  created_at: string | null;
  due_at: string | null;
  is_overdue: boolean;
  status_code: string;
  status_label: string;
  priority_label: string;
  sla_label: string;
  row_version: number;
  context: { label: string; value: string }[];
  history: { at: string | null; user: string; decision: string; note: string }[];
  assignees: { name: string; state: string; note: string }[];
  decisions: { code: string; label: string }[];
  form_fields: { key: string; label: string; kind: string; required?: boolean }[];
  path: { label: string; state: string }[];
  requires_step_up: boolean;
  summary?: string | null;
}

export interface WorkDecideRequest {
  decision: string;
  comment: string;
  data?: Record<string, unknown> | null;
  row_version?: number | null;
  password?: string | null;
}

export interface WorkDecideResponse {
  task_id: number;
  status: string;
  closed: boolean;
  message: string;
}

export interface Colleague {
  user_id: number;
  name: string;
}
