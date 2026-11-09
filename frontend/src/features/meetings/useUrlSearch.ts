import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";

/**
 * Recherche texte synchronisée avec `?q=` (comme l'ancienne interface) :
 * conservée au rechargement et partageable. L'URL est écrite `delay` ms après
 * la dernière frappe (remplacement d'historique, retour en page 1) ; une
 * navigation externe (lien, retour arrière) met le champ à jour.
 */
export function useUrlSearch(delay = 300): [string, (value: string) => void] {
  const [search, setSearch] = useSearchParams();
  const urlQ = search.get("q") ?? "";
  const [q, setQ] = useState(urlQ);
  const [seen, setSeen] = useState(urlQ);
  if (urlQ !== seen) {
    setSeen(urlQ);
    setQ(urlQ);
  }
  // Dernière version de `setSearch` (ses paramètres courants) pour l'écriture différée.
  const setSearchRef = useRef(setSearch);
  useEffect(() => { setSearchRef.current = setSearch; });
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const onChange = useCallback((value: string) => {
    setQ(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setSearchRef.current((s) => {
      if (value.trim()) s.set("q", value);
      else s.delete("q");
      s.delete("page");
      return s;
    }, { replace: true }), delay);
  }, [delay]);

  return [q, onChange];
}
