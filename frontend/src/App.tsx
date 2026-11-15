import { useEffect, useState } from "react";
import { Login } from "./components/Login";
import { Layout, type PageKey } from "./components/Layout";
import { ActionsPage } from "./pages/ActionsPage";
import { ApiTestingPage } from "./pages/ApiTestingPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SessionsPage } from "./pages/SessionsPage";
import { WorkspacePage } from "./pages/WorkspacePage";
import { adminKey, api } from "./services/api";

const PAGES: PageKey[] = ["overview", "sessions", "actions", "workspace", "testing"];

function pageFromHash(): PageKey {
  const key = window.location.hash.replace("#/", "").split("/")[0] as PageKey;
  return PAGES.includes(key) ? key : "overview";
}

export default function App() {
  const [signedIn, setSignedIn] = useState(false);
  const [checking, setChecking] = useState(true);
  const [devTools, setDevTools] = useState(false);
  const [environment, setEnvironment] = useState("");
  const [page, setPage] = useState<PageKey>(pageFromHash);
  const [focusSession, setFocusSession] = useState<string | null>(null);

  const accept = (info: { dev_tools_enabled: boolean; environment: string }) => {
    setDevTools(info.dev_tools_enabled);
    setEnvironment(info.environment);
    setSignedIn(true);
  };

  useEffect(() => {
    const key = adminKey.get();
    if (!key) {
      setChecking(false);
      return;
    }
    api.checkKey(key).then(accept).catch(() => adminKey.clear()).finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = (next: PageKey) => {
    window.location.hash = `#/${next}`;
    setPage(next);
  };

  if (checking) return <div className="p-10 text-sm text-slate-500">Loading…</div>;
  if (!signedIn) return <Login onSuccess={accept} />;

  const openSession = (id: string) => {
    setFocusSession(id);
    navigate("sessions");
  };

  return (
    <Layout page={page} onNavigate={navigate} devTools={devTools} environment={environment}
      onSignOut={() => { adminKey.clear(); setSignedIn(false); }}>
      {page === "overview" && <OverviewPage onOpenSession={openSession} />}
      {page === "sessions" && <SessionsPage focus={focusSession} onFocus={setFocusSession} />}
      {page === "actions" && <ActionsPage onOpenSession={openSession} />}
      {page === "workspace" && <WorkspacePage />}
      {page === "testing" && (devTools ? <ApiTestingPage onOpenSession={openSession} /> : (
        <div className="card p-6 text-sm text-slate-600">
          API testing is a development-only tool and is disabled on this server.
        </div>
      ))}
    </Layout>
  );
}
