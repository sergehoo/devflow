/** Contexte technique minimal et explicite (aucun cookie, stockage, champ ni paramètre d'URL). */
export function technicalContext(extra: Record<string, string | number | boolean> = {}) {
  return {
    page: `${window.location.origin}${window.location.pathname}`,
    metadata: {
      user_agent: navigator.userAgent.slice(0, 300), language: navigator.language,
      viewport: `${window.innerWidth}x${window.innerHeight}`, ...extra,
    },
  };
}
