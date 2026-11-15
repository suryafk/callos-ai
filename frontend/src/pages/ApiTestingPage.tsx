import { useEffect, useMemo, useState } from "react";
import { Badge, ErrorBanner, Json, MockBadge, PageHeader, StatusBadge } from "../components/ui";
import { api } from "../services/api";
import type { ToolInfo, ToolResponse } from "../types";

interface LogEntry { id: number; caller?: string; action?: string; parameters?: Record<string, unknown>; response?: ToolResponse; note?: string; ms?: number }
interface DemoContext { code: string; actionId?: string; version?: number }
interface DemoStep { caller: string; note?: string; expect?: string; call?: (ctx: DemoContext) => { action: string; parameters: Record<string, unknown> } }

// The primary acceptance flow: ask -> act -> change of mind -> approve.
const DEMO: DemoStep[] = [
  { caller: "Explain what a project retrospective is.", note: "Answered by the voice model itself. No backend call is made for general questions." },
  { caller: "Check my calendar tomorrow afternoon.", expect: "auth_required", call: () => ({ action: "check_calendar", parameters: { date: "tomorrow", part_of_day: "afternoon" } }) },
  { caller: "(says their access code)", expect: "success", call: (c) => ({ action: "verify_identity", parameters: { access_code: c.code } }) },
  { caller: "(the agent retries the calendar check)", expect: "success", call: () => ({ action: "check_calendar", parameters: { date: "tomorrow", part_of_day: "afternoon" } }) },
  { caller: "Schedule a retrospective meeting at 3 PM with my team.", expect: "awaiting_approval", call: () => ({ action: "prepare_meeting", parameters: { title: "Project retrospective", date: "tomorrow", time: "15:00", attendees: "my team" } }) },
  { caller: "Actually, make it 4 PM.", expect: "awaiting_approval", call: (c) => ({ action: "update_pending_action", parameters: { action_id: c.actionId, time: "16:00" } }) },
  { caller: "Yes, proceed.", expect: "completed", call: (c) => ({ action: "approve_action", parameters: { action_id: c.actionId, version: c.version } }) },
  { caller: "(approval repeated by mistake)", expect: "completed", call: (c) => ({ action: "approve_action", parameters: { action_id: c.actionId, version: c.version } }) },
];

const newSessionId = () => `sim-${Math.random().toString(16).slice(2, 10)}${Date.now().toString(16).slice(-4)}`;

export function ApiTestingPage({ onOpenSession }: { onOpenSession: (id: string) => void }) {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [sessionId, setSessionId] = useState(newSessionId);
  const [toolName, setToolName] = useState("check_calendar");
  const [values, setValues] = useState<Record<string, string>>({ date: "tomorrow", part_of_day: "afternoon" });
  const [code, setCode] = useState("");
  const [log, setLog] = useState<LogEntry[]>([]);
  const [step, setStep] = useState(0);
  const [ctx, setCtx] = useState<DemoContext>({ code: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stopped, setStopped] = useState<string | null>(null);

  useEffect(() => { api.tools().then(setTools).catch((e: Error) => setError(e.message)); }, []);
  const tool = useMemo(() => tools.find((t) => t.name === toolName), [tools, toolName]);

  const send = async (action: string, parameters: Record<string, unknown>, caller?: string): Promise<ToolResponse | null> => {
    setBusy(true);
    setError(null);
    const started = performance.now();
    try {
      const shown = { ...parameters, ...(parameters.access_code ? { access_code: "••••••" } : {}) };
      const response = await api.simulate(sessionId, action, parameters);
      setLog((l) => [{ id: Date.now(), caller, action, parameters: shown, response, ms: performance.now() - started }, ...l]);
      return response;
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const sendManual = () => {
    const parameters: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(values)) if (v.trim() !== "") parameters[k] = v.trim();
    void send(toolName, parameters);
  };

  const runDemoStep = async () => {
    const current = DEMO[step];
    if (!current.call) {
      setLog((l) => [{ id: Date.now(), caller: current.caller, note: current.note }, ...l]);
      setStep(step + 1);
      return;
    }
    const context = { ...ctx, code };
    const { action, parameters } = current.call(context);
    const response = await send(action, parameters, current.caller);
    if (!response) return;
    if (current.expect && response.status !== current.expect) {
      // Stop rather than carry on with a state the script did not expect (for example a slot that is already taken).
      setStopped(`Step ${step + 1} returned "${response.status}" instead of "${current.expect}", so the guided demo stopped. ` +
        `The backend's answer is in the log below. Use "Reset demo data" for a clean workspace, then start a new call.`);
      return;
    }
    setCtx({ ...context, actionId: response.action_id ?? context.actionId, version: response.version ?? context.version });
    setStep(step + 1);
  };

  const restart = () => { setSessionId(newSessionId()); setLog([]); setStep(0); setCtx({ code: "" }); setStopped(null); };

  const reset = async () => {
    if (!window.confirm("Delete ALL sessions, actions and workspace changes, and restore the original demo data?")) return;
    setBusy(true);
    try { await api.resetDemo(); restart(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const needsCode = step <= 2;  // the access code is used by step 3

  return (
    <>
      <PageHeader title="API testing"
        subtitle="Development-only. Sends tool requests through the same allowlist, authorization and approval checks as a real call — it grants no extra access. These are simulated tool calls, not phone calls."
        actions={<><Badge tone="amber">development only</Badge><MockBadge /></>} />
      <ErrorBanner message={error} />

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-5">
          <h2 className="text-sm font-semibold">Guided demo: ask → act → change → approve</h2>
          <p className="mt-1 text-xs text-slate-500">Plays the primary acceptance flow one step at a time on a fresh call.</p>
          <ol className="mt-3 space-y-1.5 text-sm">
            {DEMO.map((s, i) => (
              <li key={i} className={`flex gap-2 ${i < step ? "text-slate-400" : i === step ? "font-medium text-slate-900" : "text-slate-500"}`}>
                <span className="w-5 shrink-0 tabular-nums">{i < step ? "✓" : `${i + 1}.`}</span><span>{s.caller}</span>
              </li>
            ))}
          </ol>
          {needsCode && (
            <div className="mt-4">
              <label className="label" htmlFor="demo-code">Demo access code (CALLOS_DEMO_USER_PIN from your .env)</label>
              <input id="demo-code" className="input" type="password" autoComplete="off" inputMode="numeric" value={code}
                onChange={(e) => setCode(e.target.value)} placeholder="6-digit demo code" />
            </div>
          )}
          {stopped && <p role="alert" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{stopped}</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            {step < DEMO.length ? (
              <button className="btn btn-primary" disabled={busy || Boolean(stopped) || (step === 2 && !code.trim())} onClick={runDemoStep}>
                {busy ? "Sending…" : `Run step ${step + 1}`}
              </button>
            ) : <Badge tone="green">Demo finished</Badge>}
            <button className="btn btn-secondary" disabled={busy} onClick={restart}>New call</button>
            <button className="btn btn-secondary" onClick={() => onOpenSession(sessionId)}>View this session</button>
          </div>
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-semibold">Send a single tool request</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="sid">Session (call) ID</label>
              <input id="sid" className="input font-mono" value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="tool">Tool</label>
              <select id="tool" className="input" value={toolName} onChange={(e) => { setToolName(e.target.value); setValues({}); }}>
                {tools.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
              </select>
            </div>
          </div>
          {tool && (
            <>
              <p className="mt-3 text-xs text-slate-500">
                {tool.description} {tool.requires_auth ? "Needs a verified caller." : "No verification needed."}
                {tool.scope && <> Scope: <code>{tool.scope}</code>.</>}
              </p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {Object.keys(tool.parameters).map((name) => (
                  <div key={name}>
                    <label className="label" htmlFor={`p-${name}`}>{name}{tool.required.includes(name) && <span className="text-rose-600"> *</span>}</label>
                    <input id={`p-${name}`} className="input" type={name === "access_code" ? "password" : "text"} autoComplete="off"
                      value={values[name] ?? ""} onChange={(e) => setValues({ ...values, [name]: e.target.value })} />
                  </div>
                ))}
                {Object.keys(tool.parameters).length === 0 && <p className="text-xs text-slate-500">This tool takes no parameters.</p>}
              </div>
            </>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <button className="btn btn-primary" disabled={busy || !tool} onClick={sendManual}>Send request</button>
            <button className="btn btn-secondary text-rose-700" disabled={busy} onClick={reset}>Reset demo data…</button>
          </div>
        </section>
      </div>

      <section className="card mt-4 overflow-hidden">
        <div className="border-b border-slate-200 px-5 py-3 text-sm font-semibold">Conversation and tool log <span className="font-normal text-slate-500">(newest first)</span></div>
        {log.length === 0 && <div className="px-5 py-8 text-center text-sm text-slate-500">Nothing sent yet.</div>}
        <ul className="divide-y divide-slate-100">
          {log.map((entry) => (
            <li key={entry.id} className="px-5 py-4 text-sm">
              {entry.caller && <div className="text-slate-500"><span className="font-medium text-slate-700">Caller:</span> {entry.caller}</div>}
              {entry.note && <div className="mt-1 rounded-lg bg-slate-50 px-3 py-2 text-slate-600">{entry.note}</div>}
              {entry.response && (
                <>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <code className="text-xs">{entry.action}</code>
                    <StatusBadge status={entry.response.status} />
                    <span className="text-xs text-slate-500">state: {entry.response.workflow_state} · {entry.ms?.toFixed(0)} ms round trip</span>
                  </div>
                  <div className="mt-2 rounded-lg border border-indigo-100 bg-indigo-50/60 px-3 py-2 text-slate-800">
                    <span className="font-medium text-indigo-800">CallOS says:</span> {entry.response.speech}
                  </div>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs font-medium text-slate-500">Request and full response</summary>
                    <div className="mt-2 grid gap-3 lg:grid-cols-2">
                      <Json value={{ action: entry.action, parameters: entry.parameters }} />
                      <Json value={entry.response} />
                    </div>
                  </details>
                </>
              )}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
