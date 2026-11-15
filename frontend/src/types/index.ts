export interface ActionRecord {
  action_id: string;
  session_id: string;
  user_id: string;
  type: string;
  parameters: Record<string, unknown>;
  summary: string;
  version: number;
  status: string;
  requires_approval: boolean;
  risk_flags: string[];
  approval_status: string;
  execution_mode: string;
  result: Record<string, unknown> | null;
  steps: Array<{ step: string; status: string; message?: string; detail?: Record<string, unknown> }>;
  error: string | null;
  created_at: string;
  updated_at: string;
  executed_at: string | null;
  expires_at: string;
}

export interface SessionRecord {
  session_id: string;
  channel: string;
  workflow_state: string;
  auth_level: string;
  user_id: string | null;
  user_name: string | null;
  started_at: string;
  last_activity_at: string;
  authenticated_at: string | null;
  tool_call_count: number;
  failed_auth_attempts: number;
  action_count?: number;
}

export interface AuditEvent {
  id: number;
  session_id: string | null;
  action_id: string | null;
  user_id: string | null;
  event_type: string;
  tool: string | null;
  outcome: string | null;
  detail: Record<string, unknown>;
  correlation_id: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface Overview {
  total_sessions: number;
  authenticated_sessions: number;
  total_actions: number;
  completed_actions: number;
  failed_actions: number;
  pending_approvals: number;
  cancelled_actions: number;
  tool_calls: number;
  recent_actions: ActionRecord[];
  tool_latency: { samples: number; median_ms: number; p95_ms: number; note: string } | null;
  environment: string;
  integration_mode: string;
  dev_tools_enabled: boolean;
  demo_auth_enabled: boolean;
}

export interface SessionDetail {
  session: SessionRecord;
  pending_actions: ActionRecord[];
  actions: ActionRecord[];
}

export interface Workspace {
  execution_mode: string;
  users: Array<{ user_id: string; display_name: string }>;
  user: { user_id: string; display_name: string; email: string; timezone: string; scopes: string[] } | null;
  emails: Array<{
    id: string; folder: string; from: string; from_address: string; to: string[]; subject: string;
    body: string; unread: boolean; received: string; created_by: string;
  }>;
  events: Array<{ id: string; title: string; start: string; end: string; attendees: string[]; created_by: string }>;
  documents: Array<{ id: string; title: string; content: string; tags: string[]; updated: string }>;
  tasks: Array<{ id: string; title: string; notes: string | null; status: string; due_date: string | null; created_by: string }>;
}

export interface ToolInfo {
  name: string;
  kind: string;
  scope: string | null;
  requires_auth: boolean;
  description: string;
  dedicated_endpoint: string | null;
  parameters: Record<string, { type?: string; title?: string; default?: unknown; anyOf?: Array<{ type?: string }> }>;
  required: string[];
}

export interface ToolResponse {
  ok: boolean;
  status: string;
  action?: string;
  speech: string;
  data?: unknown;
  action_id?: string;
  version?: number;
  requires_approval?: boolean;
  summary?: string;
  execution_mode?: string;
  workflow_state?: string;
  auth_level?: string;
  correlation_id?: string;
}
