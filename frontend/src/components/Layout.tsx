import type { ReactNode } from "react";
import { Logo } from "./Login";
import { Badge } from "./ui";

export type PageKey = "overview" | "sessions" | "actions" | "workspace" | "testing";

const NAV: Array<{ key: PageKey; label: string; hint: string; dev?: boolean }> = [
  { key: "overview", label: "Overview", hint: "Totals and recent activity" },
  { key: "sessions", label: "Sessions", hint: "Calls, state and audit trail" },
  { key: "actions", label: "Actions", hint: "Approvals and results" },
  { key: "workspace", label: "Demo workspace", hint: "Mock email, calendar, docs, tasks" },
  { key: "testing", label: "API testing", hint: "Simulate tool calls", dev: true },
];

export function Layout(props: {
  page: PageKey; onNavigate: (p: PageKey) => void; devTools: boolean; environment: string;
  onSignOut: () => void; children: ReactNode;
}) {
  const items = NAV.filter((n) => !n.dev || props.devTools);
  return (
    <div className="min-h-screen lg:flex">
      <aside className="border-b border-slate-200 bg-white lg:fixed lg:inset-y-0 lg:w-64 lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-3 px-5 py-4">
          <Logo />
          <div className="min-w-0">
            <div className="font-semibold leading-tight">CallOS AI</div>
            <div className="truncate text-xs text-slate-500">Admin dashboard</div>
          </div>
          <button onClick={props.onSignOut} className="ml-auto text-xs font-medium text-slate-500 hover:text-slate-800 lg:hidden">
            Sign out
          </button>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible" aria-label="Main">
          {items.map((item) => {
            const active = item.key === props.page;
            return (
              <button key={item.key} onClick={() => props.onNavigate(item.key)} aria-current={active ? "page" : undefined} aria-label={item.label}
                className={`shrink-0 rounded-lg px-3 py-2 text-left transition ${active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"}`}>
                <div className="flex items-center gap-2 text-sm font-medium">
                  {item.label}
                  {item.dev && <Badge tone="amber">dev</Badge>}
                </div>
                <div className="hidden text-xs text-slate-500 lg:block">{item.hint}</div>
              </button>
            );
          })}
        </nav>
        <div className="hidden px-5 py-4 lg:absolute lg:inset-x-0 lg:bottom-0 lg:block lg:border-t lg:border-slate-200">
          <div className="mb-2 flex flex-wrap gap-1.5">
            <Badge tone="indigo">mock integrations</Badge>
            <Badge>{props.environment || "unknown"}</Badge>
          </div>
          <button onClick={props.onSignOut} className="text-xs font-medium text-slate-500 hover:text-slate-800">
            Sign out
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 lg:ml-64 lg:py-8">
        <div className="mx-auto max-w-6xl">{props.children}</div>
      </main>
    </div>
  );
}
