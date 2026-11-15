import { useState, type ReactNode } from "react";
import { Badge, Empty, ErrorBanner, MockBadge, Mono, PageHeader, StatusBadge } from "../components/ui";
import { api } from "../services/api";
import { usePolling } from "../services/usePolling";

function Panel({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <section className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
        <h2 className="text-sm font-semibold">{title} <span className="font-normal text-slate-500">({count})</span></h2>
        <MockBadge />
      </div>
      <div className="max-h-[28rem] divide-y divide-slate-100 overflow-y-auto">{children}</div>
    </section>
  );
}

const ByCallOS = () => <Badge tone="green">created by CallOS</Badge>;

export function WorkspacePage() {
  const [userId, setUserId] = useState<string | undefined>();
  const [openItem, setOpenItem] = useState<string | null>(null);
  const { data, error, loading } = usePolling(() => api.workspace(userId), [userId]);
  const toggle = (id: string) => setOpenItem(openItem === id ? null : id);

  return (
    <>
      <PageHeader title="Demo workspace"
        subtitle="Simulated email, calendar, documents and tasks stored in the CallOS database. This is not a real mailbox or calendar. Items created by an approved phone request are marked."
        actions={data && (
          <select aria-label="Workspace user" className="input w-auto" value={data.user?.user_id ?? ""} onChange={(e) => setUserId(e.target.value)}>
            {data.users.map((u) => <option key={u.user_id} value={u.user_id}>{u.display_name}</option>)}
          </select>
        )} />
      <ErrorBanner message={error} />
      {loading && !data && <div className="text-sm text-slate-500">Loading…</div>}
      {data?.user && (
        <>
          <div className="card mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3 text-sm">
            <div><span className="text-slate-500">Account</span> <span className="font-medium">{data.user.display_name}</span> · {data.user.email}</div>
            <div><span className="text-slate-500">Timezone</span> {data.user.timezone}</div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-slate-500">Permissions</span>
              {data.user.scopes.map((s) => <Badge key={s} tone={/write|send/.test(s) ? "amber" : "slate"}>{s}</Badge>)}
            </div>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Calendar" count={data.events.length}>
              {data.events.length === 0 && <Empty>No events.</Empty>}
              {data.events.map((ev) => (
                <div key={ev.id} className="px-5 py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900">{ev.title}</span>
                    {ev.created_by === "callos" && <ByCallOS />}
                  </div>
                  <div className="text-slate-600">{ev.start} – {ev.end.split(" ").slice(-2).join(" ")}</div>
                  {ev.attendees.length > 0 && <div className="text-xs text-slate-500">with {ev.attendees.join(", ")}</div>}
                </div>
              ))}
            </Panel>
            <Panel title="Tasks" count={data.tasks.length}>
              {data.tasks.length === 0 && <Empty>No tasks.</Empty>}
              {data.tasks.map((t) => (
                <div key={t.id} className="flex flex-wrap items-center gap-2 px-5 py-3 text-sm">
                  <span className={`font-medium ${t.status === "completed" ? "text-slate-400 line-through" : "text-slate-900"}`}>{t.title}</span>
                  <StatusBadge status={t.status === "open" ? "pending" : "completed"} />
                  {t.created_by === "callos" && <ByCallOS />}
                  <span className="ml-auto text-xs text-slate-500">{t.due_date ? `due ${t.due_date}` : "no due date"}</span>
                </div>
              ))}
            </Panel>
            <Panel title="Email" count={data.emails.length}>
              {data.emails.length === 0 && <Empty>No email.</Empty>}
              {data.emails.map((e) => (
                <button key={e.id} onClick={() => toggle(e.id)} className="block w-full px-5 py-3 text-left text-sm hover:bg-slate-50">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`${e.unread ? "font-semibold text-slate-900" : "text-slate-700"}`}>{e.subject}</span>
                    {e.folder === "sent" ? <Badge tone="blue">sent</Badge> : e.unread && <Badge tone="amber">unread</Badge>}
                    {e.created_by === "callos" && <ByCallOS />}
                  </div>
                  <div className="text-xs text-slate-500">
                    {e.folder === "sent" ? `to ${e.to.join(", ")}` : `from ${e.from} <${e.from_address}>`} · {e.received} · <Mono>{e.id}</Mono>
                  </div>
                  {openItem === e.id && <p className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-slate-700">{e.body}</p>}
                </button>
              ))}
            </Panel>
            <Panel title="Documents" count={data.documents.length}>
              {data.documents.length === 0 && <Empty>No documents.</Empty>}
              {data.documents.map((d) => (
                <button key={d.id} onClick={() => toggle(d.id)} className="block w-full px-5 py-3 text-left text-sm hover:bg-slate-50">
                  <div className="font-medium text-slate-900">{d.title}</div>
                  <div className="text-xs text-slate-500">updated {d.updated} · {d.tags.join(", ")} · <Mono>{d.id}</Mono></div>
                  {openItem === d.id && <p className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-slate-700">{d.content}</p>}
                </button>
              ))}
            </Panel>
          </div>
          <p className="mt-4 text-xs text-slate-500">
            Two seeded items (one email, one document) deliberately contain instructions aimed at an AI assistant. They
            are there to show that retrieved content is treated as data and cannot trigger actions.
          </p>
        </>
      )}
    </>
  );
}
