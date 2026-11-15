import { Fragment, useState } from "react";
import type { ActionRecord } from "../types";
import { Badge, Empty, formatTime, Json, MockBadge, Mono, StatusBadge } from "./ui";

const TYPE_LABEL: Record<string, string> = {
  create_meeting: "Create meeting", send_email: "Send email", create_task: "Create task", complete_task: "Complete task",
};

export function ActionTable({ actions, onOpenSession, compact = false }: {
  actions: ActionRecord[]; onOpenSession?: (id: string) => void; compact?: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (!actions.length) return <Empty>No actions yet. Actions appear when a caller asks CallOS to change something.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200">
        <thead className="bg-slate-50">
          <tr>
            <th className="th">Action</th>
            <th className="th">What it does</th>
            <th className="th">Approval</th>
            <th className="th">Result</th>
            <th className="th">Updated</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {actions.map((a) => (
            <Fragment key={a.action_id}>
              <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(open === a.action_id ? null : a.action_id)}>
                <td className="td">
                  <div className="font-medium text-slate-900">{TYPE_LABEL[a.type] ?? a.type}</div>
                  <Mono>{a.action_id} · v{a.version}</Mono>
                </td>
                <td className="td max-w-md">
                  <div className={compact ? "line-clamp-2" : ""}>{a.summary}</div>
                  {a.risk_flags.length > 0 && <div className="mt-1"><Badge tone="red">risk: {a.risk_flags.join(", ")}</Badge></div>}
                </td>
                <td className="td"><StatusBadge status={a.approval_status} /></td>
                <td className="td">
                  <StatusBadge status={a.status} />
                  {a.status === "completed" && Boolean(a.result?.verified) && (
                    <div className="mt-1 text-xs text-emerald-700">verified by read-back</div>
                  )}
                </td>
                <td className="td whitespace-nowrap text-xs text-slate-500">{formatTime(a.updated_at)}</td>
              </tr>
              {open === a.action_id && (
                <tr className="bg-slate-50/70">
                  <td colSpan={5} className="px-4 py-4">
                    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                      <MockBadge />
                      <span>Session</span>
                      {onOpenSession ? (
                        <button className="font-mono text-indigo-700 underline" onClick={(e) => { e.stopPropagation(); onOpenSession(a.session_id); }}>
                          {a.session_id}
                        </button>
                      ) : <Mono>{a.session_id}</Mono>}
                      <span>· created {formatTime(a.created_at)}</span>
                      {a.executed_at && <span>· executed {formatTime(a.executed_at)}</span>}
                      {a.status === "awaiting_approval" && <span>· expires {formatTime(a.expires_at)}</span>}
                    </div>
                    {a.error && <div className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">{a.error}</div>}
                    <div className="grid gap-4 lg:grid-cols-2">
                      <div>
                        <div className="label">Parameters (version {a.version})</div>
                        <Json value={a.parameters} />
                      </div>
                      <div>
                        <div className="label">Execution result</div>
                        <Json value={a.result ?? { note: "Not executed" }} />
                      </div>
                    </div>
                    {a.steps.length > 0 && (
                      <div className="mt-4">
                        <div className="label">Steps</div>
                        <ol className="space-y-1 text-sm">
                          {a.steps.map((s, i) => (
                            <li key={s.step} className="flex flex-wrap items-center gap-2">
                              <span className="text-slate-400">{i + 1}.</span>
                              <span className="font-medium">{s.step.replace(/_/g, " ")}</span>
                              <StatusBadge status={s.status === "success" ? "completed" : s.status} />
                              {s.message && <span className="text-slate-500">{s.message}</span>}
                            </li>
                          ))}
                        </ol>
                      </div>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
