import { Fragment, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const PROSE = cn(
  "text-sm leading-7 text-foreground/90 break-words",
  "[&_p]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5",
  "[&_strong]:font-semibold [&_strong]:text-foreground [&_a]:text-brand [&_a]:underline",
  "[&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-semibold",
  "[&_table]:my-2 [&_table]:border-collapse [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:bg-muted [&_th]:px-2 [&_th]:py-1",
);

/**
 * Texte riche saisi dans l'application, déjà nettoyé côté Django par le même
 * filtre que les templates (`safe_html` : bleach, liste blanche, XSS bloqué).
 */
export function RichHtml({ html, empty = "—", className }: { html: string; empty?: string; className?: string }) {
  if (!html) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return <div className={cn(PROSE, className)} dangerouslySetInnerHTML={{ __html: html }} />;
}

/** Gras / italique / code en ligne, sans HTML injecté. */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const token = m[0];
    if (token.startsWith("**") || token.startsWith("__")) out.push(<strong key={i++}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith("`")) out.push(<code key={i++} className="rounded bg-muted px-1 text-[0.85em]">{token.slice(1, -1)}</code>);
    else out.push(<em key={i++}>{token.slice(1, -1)}</em>);
    last = m.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/**
 * Rendu Markdown minimal (titres, listes, paragraphes, gras/italique) des
 * comptes rendus IA — construit des éléments React (aucun `innerHTML`).
 */
export function Markdown({ text, className }: { text: string; className?: string }) {
  const blocks: ReactNode[] = [];
  const state: { list: { ordered: boolean; items: string[] } | null; para: string[] } = { list: null, para: [] };
  const flushPara = () => {
    if (state.para.length) {
      blocks.push(<p key={blocks.length}>{state.para.map((l, i) => <Fragment key={i}>{i > 0 && <br />}{inline(l)}</Fragment>)}</p>);
    }
    state.para = [];
  };
  const flushList = () => {
    const list = state.list;
    if (list) {
      const items = list.items.map((it, i) => <li key={i}>{inline(it)}</li>);
      blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    }
    state.list = null;
  };
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) { flushPara(); flushList(); continue; }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const item = line.match(/^\s*(?:([-*+])|\d+[.)])\s+(.*)$/);
    if (heading) {
      flushPara(); flushList();
      const level = heading[1]?.length ?? 1;
      const content = inline(heading[2] ?? "");
      blocks.push(level <= 1 ? <h1 key={blocks.length}>{content}</h1> : level === 2 ? <h2 key={blocks.length}>{content}</h2> : <h3 key={blocks.length}>{content}</h3>);
    } else if (item) {
      flushPara();
      const ordered = !item[1];
      if (!state.list || state.list.ordered !== ordered) { flushList(); state.list = { ordered, items: [] }; }
      state.list.items.push(item[2] ?? "");
    } else {
      flushList();
      state.para.push(line);
    }
  }
  flushPara();
  flushList();
  return <div className={cn(PROSE, "[&_h1]:mt-3 [&_h2]:mt-3 [&_h3]:mt-2", className)}>{blocks}</div>;
}
