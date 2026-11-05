/** N'accepte qu'une redirection interne à l'application (pas d'open redirect). */
export function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}
