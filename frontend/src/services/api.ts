import type {
  ActionRecord, AuditEvent, Overview, SessionDetail, SessionRecord, ToolInfo, ToolResponse, Workspace,
} from "../types";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const KEY_STORAGE = "callos.adminKey";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// The admin key is typed by the operator and kept only for this browser tab (sessionStorage).
export const adminKey = {
  get: () => sessionStorage.getItem(KEY_STORAGE) ?? "",
  set: (key: string) => sessionStorage.setItem(KEY_STORAGE, key),
  clear: () => sessionStorage.removeItem(KEY_STORAGE),
};

async function request<T>(path: string, init: RequestInit = {}, key = adminKey.get()): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", "X-Admin-Key": key, ...(init.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "Cannot reach the CallOS backend. Is it running?");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body as T;
}

export const api = {
  health: () => request<{ status: string; environment: string; database: string }>("/health"),
  checkKey: (key: string) => request<Overview>("/api/admin/overview", {}, key),
  overview: () => request<Overview>("/api/admin/overview"),
  sessions: () => request<{ sessions: SessionRecord[] }>("/api/admin/sessions").then((r) => r.sessions),
  session: (id: string) => request<SessionDetail>(`/api/sessions/${encodeURIComponent(id)}`),
  sessionEvents: (id: string) =>
    request<{ events: AuditEvent[] }>(`/api/sessions/${encodeURIComponent(id)}/events`).then((r) => r.events),
  actions: (status?: string) =>
    request<{ actions: ActionRecord[] }>(`/api/admin/actions${status ? `?status=${status}` : ""}`).then(
      (r) => r.actions,
    ),
  workspace: (userId?: string) =>
    request<Workspace>(`/api/admin/workspace${userId ? `?user_id=${encodeURIComponent(userId)}` : ""}`),
  tools: () => request<{ tools: ToolInfo[] }>("/api/admin/tools").then((r) => r.tools),
  simulate: (session_id: string, action: string, parameters: Record<string, unknown>) =>
    request<ToolResponse>("/api/dev/simulate", {
      method: "POST",
      body: JSON.stringify({ session_id, action, parameters }),
    }),
  resetDemo: () => request<{ ok: boolean }>("/api/dev/reset", { method: "POST" }),
};
