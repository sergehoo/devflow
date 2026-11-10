import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, Send, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";

interface Msg { role: "user" | "assistant"; content: string; provider?: string }
interface Welcome { context_summary?: Record<string, unknown> | string; suggestions?: string[] }
/** Suggestions du service : pictogrammes retirés (charte sans emoji). */
const clean = (text: string) => text.replace(/[\p{Extended_Pictographic}\uFE0F\u200D]/gu, "").trim();

interface SendResult { session_id: number; assistant_message: { content: string; used_provider: string } }

/** Assistant IA (même service que le chat historique : AIChatService, quota IA côté Django). Texte brut uniquement. */
export function AssistantPage() {
  const welcome = useQuery({ queryKey: ["assistant", "welcome"], queryFn: ({ signal }) => api<Welcome>("assistant/welcome/", { signal }), staleTime: 300_000 });
  const [session, setSession] = useState<number | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [messages]);
  const send = useMutation({
    mutationFn: (message: string) => api<SendResult>("assistant/send/", { method: "POST", body: { message, session_id: session, page_context: { page: "assistant" } } }),
    onSuccess: (r) => { setSession(r.session_id); setMessages((m) => [...m, { role: "assistant", content: r.assistant_message.content, provider: r.assistant_message.used_provider }]); },
    onError: (e) => { toast.error(e.message); setMessages((m) => m.slice(0, -1)); },
  });
  const ask = (message: string) => {
    const q = message.trim();
    if (!q || send.isPending) return;
    setMessages((m) => [...m, { role: "user", content: q }]);
    setText("");
    send.mutate(q);
  };
  const close = async () => {
    if (session) await api(`assistant/sessions/${session}/close/`, { method: "POST", body: {} }).catch(() => undefined);
    setSession(null); setMessages([]);
  };
  const submit = (e: FormEvent) => { e.preventDefault(); ask(text); };
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="IA" title="Assistant DevFlow" description="Questions sur vos projets, tâches, budgets et équipes (données de votre workspace uniquement)."
        actions={session ? <Button variant="outline" onClick={() => void close()}><X />Nouvelle conversation</Button> : undefined} />
      <Card className="flex h-[calc(100dvh-16rem)] min-h-[420px] flex-col overflow-hidden">
        <div className="flex-1 space-y-3 overflow-y-auto p-5" aria-live="polite">
          {!messages.length && (
            <div className="mx-auto max-w-xl py-8 text-center">
              <span className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground"><Bot className="size-6" aria-hidden="true" /></span>
              <p className="mt-3 font-semibold">Comment puis-je vous aider ?</p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {(welcome.data?.suggestions ?? []).slice(0, 6).map((s) => (
                  <Button key={s} size="sm" variant="outline" onClick={() => ask(clean(s))}><Sparkles />{clean(s)}</Button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={cn("max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm", m.role === "user" ? "ml-auto bg-primary-faint" : "bg-muted")}>
              {m.content}
              {m.provider && <span className="mt-1 block text-[10px] text-muted-foreground">{m.provider}</span>}
            </div>
          ))}
          {send.isPending && <p className="text-xs text-muted-foreground">L'assistant réfléchit…</p>}
          <div ref={end} />
        </div>
        <form onSubmit={submit} className="flex items-end gap-2 border-t p-3 pr-20">
          <label htmlFor="assistant-input" className="sr-only">Votre question</label>
          <Textarea id="assistant-input" value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} rows={2}
            placeholder="Posez votre question…" className="min-h-12 flex-1"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(text); } }} />
          <Button type="submit" disabled={send.isPending || !text.trim()} aria-label="Envoyer"><Send /></Button>
        </form>
      </Card>
    </div>
  );
}
