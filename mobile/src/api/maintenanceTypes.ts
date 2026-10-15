/** R312: نگهداری و تعمیرات (موبایل تکنسین) — همان پاسخ‌های peecha_api/routers/maintenance.py */

export interface MntWorkOrderBrief {
  work_order_id: number;
  wo_no: number;
  title: string;
  status_label: string;
}

export interface MntEquipmentCard {
  asset_id: number;
  code: string;
  name: string;
  serial_no: string | null;
  manufacturer: string | null;
  model: string | null;
  location: string;
  line: string;
  status_label: string;
  criticality_label: string;
  down_now: boolean;
  down_since: string | null;
  safety_notes: string | null;
  open_requests: number;
  open_work_orders: MntWorkOrderBrief[];
}

export interface MntRequestPayload {
  asset_id?: number | null;
  code?: string | null;
  title: string;
  description?: string | null;
  machine_stopped: boolean;
  severity_code: string;
  probable_cause?: string | null;
  failure_at?: string | null;
  scanned: boolean;
}

export interface MntWorkOrderRow {
  work_order_id: number;
  wo_no: number;
  asset_label: string;
  title: string;
  work_type_label: string;
  priority_code: string;
  priority_label: string;
  status_code: string;
  status_label: string;
  planned_start: string | null;
  requires_shutdown: boolean;
}

export interface MntTask {
  task_id: number;
  seq: number;
  description: string;
  result_type: "CHECK" | "NUMERIC" | "TEXT";
  min_value: string | null;
  max_value: string | null;
  uom_label: string | null;
  is_mandatory: boolean;
  is_safety: boolean;
  is_done: boolean;
  value_numeric: string | null;
  value_text: string | null;
  is_ok: boolean | null;
}

export interface MntWorkOrderDetail extends MntWorkOrderRow {
  description: string | null;
  safety_instructions: string | null;
  required_skills: string | null;
  hold_reason: string | null;
  completion_note: string | null;
  verification_label: string;
  machine_down: boolean;
  tasks: MntTask[];
  parts: { item: string; planned: string | null; issued: string | null }[];
}
