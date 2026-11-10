import { ArrowLeft, Bot, Brush, Check, ExternalLink, RefreshCw, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useCopilotChat, useCopilotLogs, type CopilotLogs } from "./api";
import { COPILOT_SUGGESTIONS } from "./constants";
import { AIStatusNotice, StatusBadge } from "./shared";

interface Message { role: "user" | "assistant"; content: string; tool?: string; failed?: boolean; link?: string | null }

/**
 * Conversation conservée le temps de l'onglet (sessionStorage) — jamais de jeton ni de secret,
 * uniquement les messages échangés avec le copilote pour ce projet.
 */
const storageKey = (projectId: number) => `devflow:copilot:project:${projectId}`;

function loadHistory(projectId: number): Message[] {
  try {
    const raw = sessionStorage.getItem(storageKey(projectId));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as Message[]).filter((m) => m && typeof m.content === "string") : [];
  } catch {
    return [];
  }
}

function Chat({ projectId, data }: { projectId: number; data: CopilotLogs }) {
  const chat = useCopilotChat(projectId);
  const [history, setHistory] = useState<Message[]>(() => loadHistory(projectId));
  const [input, setInput] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try { sessionStorage.setItem(storageKey(projectId), JSON.stringify(history.slice(-50))); } catch { /* stockage indisponible */ }
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [history, projectId]);

  const send = (text: string) => {
    const message = text.trim();
    if (!message || chat.isPending) return;
    const next: Message[] = [...history, { role: "user", content: message }];
    setHistory(next);
    setInput("");
    chat.mutate(
      { message, history: next.slice(-11, -1).map((m) => ({ role: m.role, content: m.content })) },
      {
        onSuccess: (r) => {
          const action = r.actions_executed?.[0];
          setHistory((h) => [...h, {
            role: "assistant",
            content: r.message || "—",
            tool: r.type === "tool_result" || r.type === "tool_error" ? r.tool_name : undefined,
            failed: r.type === "tool_error",
            link: action?.link ?? null,
          }]);
        },
        onError: (e) => setHistory((h) => [...h, { role: "assistant", content: `Erreur : ${e.message}`, failed: true }]),
      },
    );
  };

  return (
    <Card className="flex h-[70vh] min-h-[26rem] flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <p className="flex items-center gap-2 text-sm font-semibold">
          <Bot className="size-4 text-brand" aria-hidden="true" />Copilote IA
          {data.project.methodology_label && <span className="text-xs font-normal text-muted-foreground">· spécialisé {data.project.methodology_label}</span>}
        </p>
        <Button variant="ghost" size="sm" disabled={!history.length} onClick={() => setConfirmClear(true)}><Brush />Effacer</Button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
        {history.length === 0 && (
          <div className="mx-auto max-w-sm py-8 text-center">
            <Sparkles className="mx-auto mb-2 size-7 text-brand" aria-hidden="true" />
            <p className="mb-4 text-sm font-medium">Posez vos questions ou demandez une action</p>
            <div className="space-y-2 text-left">
              {COPILOT_SUGGESTIONS.map((s) => (
                <button key={s.prompt} type="button" onClick={() => send(s.prompt)}
                  className="block w-full rounded-xl border bg-muted/40 px-3 py-2 text-left text-sm transition-colors hover:bg-hover">{s.label}</button>
              ))}
            </div>
          </div>
        )}
        {history.map((m, i) => (
          <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cn("max-w-[90%] rounded-2xl px-3.5 py-2.5 text-sm sm:max-w-[80%]",
              m.role === "user" ? "rounded-br-md bg-primary text-primary-foreground" : "rounded-bl-md bg-muted text-foreground")}>
              <p className="whitespace-pre-wrap break-words">{m.content}</p>
              {m.tool && (
                <span className={cn("mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                  m.failed ? "bg-destructive/15 text-destructive" : "bg-success/15 text-success")}>
                  {m.failed ? <X className="size-3" aria-hidden="true" /> : <Check className="size-3" aria-hidden="true" />}
                  {m.tool}{m.failed ? " (échec)" : ""}
                </span>
              )}
              {m.link && (
                <Link to={m.link} className="ml-2 inline-flex items-center gap-1 text-xs font-semibold text-brand hover:underline">
                  Ouvrir l'élément<ExternalLink className="size-3" aria-hidden="true" />
                </Link>
              )}
            </div>
          </div>
        ))}
        {chat.isPending && (
          <p className="flex items-center gap-1 text-sm text-muted-foreground" role="status">
            <span className="sr-only">Le copilote réfléchit…</span>
            {[0, 150, 300].map((d) => <span key={d} className="size-2 animate-bounce rounded-full bg-primary" style={{ animationDelay: `${d}ms` }} aria-hidden="true" />)}
          </p>
        )}
        <div ref={bottom} />
      </div>
      <form className="border-t p-3 pr-16 sm:pr-20" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <div className="flex gap-2">
          <Input aria-label="Message au copilote" placeholder="Posez votre question ou demandez une action…" value={input}
            maxLength={4000} disabled={chat.isPending} onChange={(e) => setInput(e.target.value)} />
          <Button type="submit" size="icon" className="size-11 shrink-0" aria-label="Envoyer" disabled={chat.isPending || !input.trim()}><Send /></Button>
        </div>
        <p className="mt-2 flex items-center gap-1 text-[11px] text-muted-foreground"><ShieldCheck className="size-3" aria-hidden="true" />Toutes les actions IA sont auditées dans le journal et soumises à vos droits.</p>
      </form>
      <ConfirmDialog open={confirmClear} onOpenChange={setConfirmClear} title="Effacer la conversation ?"
        description="La conversation affichée est effacée de ce navigateur. Le journal des actions IA est conservé."
        confirmLabel="Effacer" onConfirm={() => { setHistory([]); setConfirmClear(false); }} />
    </Card>
  );
}

function Logs({ data, refreshing, onRefresh }: { data: CopilotLogs; refreshing: boolean; onRefresh: () => void }) {
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <p className="text-sm text-muted-foreground">Traces des actions exécutées par le copilote : statut, résultat et durée (50 dernières).</p>
        <Button variant="outline" size="sm" disabled={refreshing} onClick={onRefresh}><RefreshCw />Actualiser</Button>
      </div>
      {data.logs.length === 0 ? <div className="p-4"><EmptyState title="Aucune action IA enregistrée pour ce projet" /></div> : (
        <ul className="divide-y">
          {data.logs.map((log) => (
            <li key={log.id} className="flex flex-wrap items-start gap-x-4 gap-y-1 px-4 py-3 text-sm">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-semibold">{log.tool_name}</span>
                  <StatusBadge status={log.status} label={log.status_label} />
                  <span className="text-xs text-muted-foreground">{formatDateTime(log.created_at)} · {log.user || "—"} · {log.duration_ms} ms</span>
                </div>
                {log.error_message && <p className="mt-1 break-words text-xs text-destructive">{log.error_message}</p>}
              </div>
              {log.affected && (
                log.affected.link
                  ? <Link to={log.affected.link} className="text-xs font-semibold text-brand hover:underline">{log.affected.type} n° {log.affected.id}</Link>
                  : <span className="text-xs text-muted-foreground">{log.affected.type} n° {log.affected.id}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Copilote IA du projet (conversation + actions auditées) et journal d'actions IA. */
export function CopilotPage() {
  const projectId = Number(useParams().id);
  const [search, setSearch] = useSearchParams();
  const tab = search.get("tab") === "logs" ? "logs" : "chat";
  const { data, isPending, isError, error, refetch, isFetching } = useCopilotLogs(projectId);
  if (isPending) return <PageSkeleton />;
  if (isError) return <ErrorState message={error.message} onRetry={() => void refetch()} />;
  const setTab = (t: string) => setSearch((s) => { if (t === "chat") s.delete("tab"); else s.set("tab", t); return s; }, { replace: true });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Copilote IA" title={data.project.name}
        description="Questions, analyses et actions (sprints, jalons, risques, tâches…) exécutées avec vos droits et tracées."
        actions={<>
          <Button variant="outline" asChild><Link to={`/projects/${projectId}`}><ArrowLeft />Retour au projet</Link></Button>
          <Button variant="outline" asChild><Link to={`/projects/${projectId}/ai-proposals`}>Propositions IA</Link></Button>
        </>} />
      <AIStatusNotice ai={data.ai} fallback="IA désactivée : le copilote ne peut pas répondre tant qu'aucun fournisseur IA n'est configuré." />
      <div role="tablist" aria-label="Copilote" className="flex gap-1">
        {[["chat", "Conversation"], ["logs", `Journal d'actions IA (${data.logs.length})`]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key!)}
            className={cn("rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors",
              tab === key ? "bg-primary/10 text-brand" : "text-muted-foreground hover:bg-hover hover:text-foreground")}>{label}</button>
        ))}
      </div>
      {tab === "chat" ? <Chat projectId={projectId} data={data} /> : <Logs data={data} refreshing={isFetching} onRefresh={() => void refetch()} />}
    </div>
  );
}
