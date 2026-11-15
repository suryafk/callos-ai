import { ActionTable } from "../components/ActionTable";
import { Empty, ErrorBanner, formatTime, Mono, PageHeader, StatusBadge } from "../components/ui";
import { api } from "../services/api";
import { usePolling } from "../services/usePolling";
import type { AuditEvent } from "../types";

const EVENT_LABEL: Record<string, string> = {
  session_started: "Session started", tool_call: "Tool call", state_changed: "State", access_denied: "Access denied",
  auth_succeeded: "Caller verified", auth_failed: "Verification failed", auth_expired: "Verification expired",
  action_prepared: "Action prepared", action_updated: "Action changed", action_approved: "Approved",
  approval_rejected: "Approval rejected", action_executed: "Executed", action_cancelled: "Cancelled",
  action_expired: "Expired", tool_rejected: "Tool rejected",
};

function describe(e: AuditEvent): string {
  const d = e.detail as Record<string, unknown>;
  switch (e.event_type) {
    case "state_changed": return `${d.from} → ${d.to}`;
    case "tool_call": return `${e.tool ?? "?"} → ${e.outcome}${e.duration_ms != null ? ` (${e.duration_ms.toFixed(1)} ms)` : ""}`;
    case "action_updated": return `version ${d.from_version} → ${d.to_version} (${(d.changed_fields as string[] | undefined)?.join(", ")})`;
    case "approval_rejected": return `approved version ${d.approved_version}, current is ${d.current_version}`;
    case "action_approved": case "action_prepared": case "action_executed": case "action_cancelled":
      return `${e.action_id} v${d.version ?? ""} ${e.outcome ?? ""}`.trim();
    case "access_denied": return `${e.tool}: ${e.outcome}`;
    case "tool_rejected": return `${e.tool ?? "(none)"}: ${e.outcome}`;
    default: return e.outcome ?? "";
  }
}

function SessionDetailPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const detail = usePolling(() => api.session(id), [id]);
  const events = usePolling(() => api.sessionEvents(id), [id]);
  const s = detail.data?.session;
  const visible = events.data ?? [];
  return (
    <div className="card mb-6 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-5 py-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold">Session detail</div>
          <Mono>{id}</Mono>
        </div>
        <button className="btn btn-secondary" onClick={onClose}>Close</button>
      </div>
      <ErrorBanner message={detail.error ?? events.error} />
      {s && (
        <div className="grid gap-x-8 gap-y-3 px-5 py-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div><div className="label">Workflow state</div><StatusBadge status={s.workflow_state} /></div>
          <div><div className="label">Caller</div>{s.user_name ?? "Not verified"} <StatusBadge status={s.auth_level} /></div>
          <div><div className="label">Started</div>{formatTime(s.started_at)}</div>
          <div><div className="label">Last activity</div>{formatTime(s.last_activity_at)}</div>
          <div><div className="label">Channel</div>{s.channel}</div>
          <div><div className="label">Tool calls</div>{s.tool_call_count}</div>
          <div><div className="label">Verified at</div>{formatTime(s.authenticated_at)}</div>
          <div><div className="label">Failed verification attempts</div>{s.failed_auth_attempts}</div>
        </div>
      )}
      <div className="border-t border-slate-200 px-5 py-3 text-sm font-semibold">Action history</div>
      <ActionTable actions={detail.data?.actions ?? []} />
      <div className="border-t border-slate-200 px-5 py-3 text-sm font-semibold">
        Audit trail <span className="font-normal text-slate-500">({visible.length} events, oldest first)</span>
      </div>
      <ol className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
        {visible.map((e) => (
          <li key={e.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-5 py-2 text-sm">
            <span className="w-36 shrink-0 text-xs tabular-nums text-slate-400">{formatTime(e.created_at)}</span>
            <span className={`w-40 shrink-0 font-medium ${e.event_type === "state_changed" ? "text-slate-400" : "text-slate-800"}`}>
              {EVENT_LABEL[e.event_type] ?? e.event_type}
            </span>
            <span className="min-w-0 flex-1 break-words text-slate-600">{describe(e)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function SessionsPage({ focus, onFocus }: { focus: string | null; onFocus: (id: string | null) => void }) {
  const { data, error, loading } = usePolling(api.sessions);
  return (
    <>
      <PageHeader title="Sessions"
        subtitle="One session per call that reached the backend. The backend stores workflow state and an audit trail — not the conversation transcript, which stays with the voice platform." />
      <ErrorBanner message={error} />
      {focus && <SessionDetailPanel id={focus} onClose={() => onFocus(null)} />}
      <div className="card overflow-hidden">
        {loading && !data ? <div className="p-6 text-sm text-slate-500">Loading…</div> : !data?.length ? (
          <Empty>No sessions yet. Use API testing, the simulator script, or a real call to create one.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th className="th">Session ID</th><th className="th">Started</th><th className="th">Caller</th>
                  <th className="th">Workflow state</th><th className="th">Tool calls</th><th className="th">Actions</th>
                  <th className="th">Channel</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.map((s) => (
                  <tr key={s.session_id} onClick={() => onFocus(s.session_id)}
                    className={`cursor-pointer hover:bg-slate-50 ${focus === s.session_id ? "bg-indigo-50/60" : ""}`}>
                    <td className="td"><Mono>{s.session_id}</Mono></td>
                    <td className="td whitespace-nowrap text-xs">{formatTime(s.started_at)}</td>
                    <td className="td">{s.user_name ?? <span className="text-slate-400">anonymous</span>}</td>
                    <td className="td"><StatusBadge status={s.workflow_state} /></td>
                    <td className="td tabular-nums">{s.tool_call_count}</td>
                    <td className="td tabular-nums">{s.action_count ?? 0}</td>
                    <td className="td">{s.channel}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
