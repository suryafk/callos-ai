import { useState } from "react";
import { ActionTable } from "../components/ActionTable";
import { ErrorBanner, MockBadge, PageHeader } from "../components/ui";
import { api } from "../services/api";
import { usePolling } from "../services/usePolling";

const FILTERS = [
  { value: "", label: "All" },
  { value: "awaiting_approval", label: "Pending approval" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "partially_completed", label: "Partly completed" },
  { value: "unknown_outcome", label: "Unconfirmed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "expired", label: "Expired" },
];

export function ActionsPage({ onOpenSession }: { onOpenSession: (id: string) => void }) {
  const [status, setStatus] = useState("");
  const { data, error, loading } = usePolling(() => api.actions(status || undefined), [status]);
  return (
    <>
      <PageHeader title="Actions" actions={<MockBadge />}
        subtitle="Every change a caller asked for: what was prepared, whether it was approved, and the verified result. Select a row for parameters, steps and the execution result." />
      <ErrorBanner message={error} />
      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button key={f.value} onClick={() => setStatus(f.value)}
            className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition ${status === f.value ? "bg-indigo-600 text-white ring-indigo-600" : "bg-white text-slate-600 ring-slate-300 hover:bg-slate-50"}`}>
            {f.label}
          </button>
        ))}
      </div>
      <div className="card overflow-hidden">
        {loading && !data ? <div className="p-6 text-sm text-slate-500">Loading…</div> : <ActionTable actions={data ?? []} onOpenSession={onOpenSession} />}
      </div>
    </>
  );
}
