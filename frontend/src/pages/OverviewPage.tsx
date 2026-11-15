import { ActionTable } from "../components/ActionTable";
import { ErrorBanner, MockBadge, PageHeader } from "../components/ui";
import { api } from "../services/api";
import { usePolling } from "../services/usePolling";

function Stat({ label, value, tone = "text-slate-900", hint }: { label: string; value: number | string; tone?: string; hint?: string }) {
  return (
    <div className="card p-5">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold tabular-nums ${tone}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function OverviewPage({ onOpenSession }: { onOpenSession: (id: string) => void }) {
  const { data, error, loading } = usePolling(api.overview);
  return (
    <>
      <PageHeader title="Overview" actions={<MockBadge />}
        subtitle="Live view of calls handled by the CallOS backend. General questions are answered by the voice agent itself; a session appears here once a caller asks for something that needs their data or an action." />
      <ErrorBanner message={error} />
      {loading && !data && <div className="text-sm text-slate-500">Loading…</div>}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <Stat label="Total sessions" value={data.total_sessions} hint={`${data.authenticated_sessions} verified`} />
            <Stat label="Total actions" value={data.total_actions} hint={`${data.cancelled_actions} cancelled`} />
            <Stat label="Completed actions" value={data.completed_actions} tone="text-emerald-700" />
            <Stat label="Failed actions" value={data.failed_actions} tone={data.failed_actions ? "text-rose-700" : "text-slate-900"} hint="failed, partial or unconfirmed" />
            <Stat label="Pending approvals" value={data.pending_approvals} tone={data.pending_approvals ? "text-amber-700" : "text-slate-900"} />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <div className="card p-5 lg:col-span-2">
              <div className="text-sm font-semibold">How a request flows</div>
              <ol className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                {["Phone call", "Bolna voice agent", "Tool call", "Policy check", "Prepare", "Caller approves", "Execute + verify", "Spoken result"].map((s, i, all) => (
                  <li key={s} className="flex items-center gap-2">
                    <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-700">{s}</span>
                    {i < all.length - 1 && <span aria-hidden="true" className="text-slate-300">→</span>}
                  </li>
                ))}
              </ol>
              <p className="mt-3 text-xs leading-relaxed text-slate-500">
                Nothing is written until the caller approves the exact version that was read to them. Email, calendar,
                documents and tasks are a simulated workspace — no real accounts are connected.
              </p>
            </div>
            <div className="card p-5">
              <div className="text-sm font-semibold">Backend tool latency</div>
              {data.tool_latency ? (
                <>
                  <div className="mt-2 text-2xl font-semibold tabular-nums">{data.tool_latency.median_ms.toFixed(1)} ms <span className="text-sm font-normal text-slate-500">median</span></div>
                  <div className="text-sm text-slate-600">p95 {data.tool_latency.p95_ms.toFixed(1)} ms · {data.tool_latency.samples} of {data.tool_calls} calls</div>
                  <p className="mt-2 text-xs text-slate-500">{data.tool_latency.note}</p>
                </>
              ) : <p className="mt-2 text-sm text-slate-500">No tool calls measured yet.</p>}
            </div>
          </div>

          <div className="card mt-4 overflow-hidden">
            <div className="border-b border-slate-200 px-5 py-3 text-sm font-semibold">Recent actions</div>
            <ActionTable actions={data.recent_actions} onOpenSession={onOpenSession} compact />
          </div>
        </>
      )}
    </>
  );
}
