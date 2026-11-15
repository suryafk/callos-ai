import { useState, type FormEvent } from "react";
import { adminKey, api, ApiError } from "../services/api";

export function Login({ onSuccess }: { onSuccess: (info: { dev_tools_enabled: boolean; environment: string }) => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const info = await api.checkKey(key.trim());
      adminKey.set(key.trim());
      onSuccess(info);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "That admin key is not correct." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-md p-8">
        <div className="mb-6 flex items-center gap-3">
          <Logo />
          <div>
            <div className="text-lg font-semibold">CallOS AI</div>
            <div className="text-xs text-slate-500">One phone call. AI for everyone. Actions when you need them.</div>
          </div>
        </div>
        <label className="label" htmlFor="admin-key">Admin key</label>
        <input id="admin-key" type="password" autoFocus autoComplete="off" className="input" value={key}
          onChange={(e) => setKey(e.target.value)} placeholder="CALLOS_ADMIN_API_KEY" />
        {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}
        <button type="submit" className="btn btn-primary mt-4 w-full" disabled={busy || !key.trim()}>
          {busy ? "Checking…" : "Open dashboard"}
        </button>
        <p className="mt-4 text-xs leading-relaxed text-slate-500">
          The key is the backend's <code>CALLOS_ADMIN_API_KEY</code> (see your <code>.env</code>). It is kept only in
          this browser tab and is sent only to the CallOS backend.
        </p>
      </form>
    </div>
  );
}

export function Logo() {
  return (
    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white">
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor" aria-hidden="true">
        <path d="M7 3c-1 0-2 1-2 2 0 8 6 14 14 14 1 0 2-1 2-2v-3l-5-2-2 2c-2-1-4-3-5-5l2-2-2-4z" />
      </svg>
    </div>
  );
}
