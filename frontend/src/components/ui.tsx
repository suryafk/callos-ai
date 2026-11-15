import type { ReactNode } from "react";

const TONES: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  red: "bg-rose-50 text-rose-700 ring-rose-600/20",
  blue: "bg-sky-50 text-sky-700 ring-sky-600/20",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-600/20",
  slate: "bg-slate-100 text-slate-600 ring-slate-500/20",
};

const STATUS_TONE: Record<string, keyof typeof TONES> = {
  completed: "green", success: "green", approved: "green", authenticated: "green", listening: "slate",
  awaiting_approval: "amber", pending: "amber", needs_auth: "amber", planning: "blue",
  understanding: "blue", gathering_data: "blue", executing: "blue",
  failed: "red", partially_completed: "red", unknown_outcome: "red", auth_failed: "red", locked: "red",
  forbidden: "red", denied: "red", unsupported_action: "red", stale_version: "red",
  cancelled: "slate", expired: "slate", anonymous: "slate",
};

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: keyof typeof TONES }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="text-slate-400">—</span>;
  return <Badge tone={STATUS_TONE[status] ?? "slate"}>{status.replace(/_/g, " ")}</Badge>;
}

export function MockBadge() {
  return <Badge tone="indigo">MOCK · simulated</Badge>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      {message}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-10 text-center text-sm text-slate-500">{children}</div>;
}

export function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-xs text-slate-600">{children}</span>;
}
