/**
 * Client HTTP unique vers Django.
 * - Session par cookie HttpOnly (credentials same-origin) : aucun jeton en localStorage.
 * - CSRF : le cookie `csrftoken` est renvoyé dans l'en-tête X-CSRFToken pour les écritures.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly data: unknown;
  constructor(status: number, message: string, data: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function getCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const base = path.startsWith("/") ? path : `/api/v1/${path}`;
  if (!params) return base;
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `${base}${base.includes("?") ? "&" : "?"}${qs}` : base;
}

function errorMessage(data: unknown, status: number): string {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    if (typeof record.detail === "string") return record.detail;
    const first = Object.entries(record)[0];
    if (first) {
      const [field, value] = first;
      const text = Array.isArray(value) ? value.join(" ") : String(value);
      return field === "non_field_errors" ? text : `${field} : ${text}`;
    }
  }
  if (status === 403) return "Action non autorisée.";
  if (status === 404) return "Élément introuvable.";
  if (status >= 500) return "Erreur serveur, réessayez dans un instant.";
  return "La requête a échoué.";
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" };
  let body: BodyInit | undefined;
  if (options.body instanceof FormData) {
    body = options.body;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  if (!SAFE_METHODS.has(method)) {
    const token = getCookie("csrftoken");
    if (token) headers["X-CSRFToken"] = token;
  }
  const response = await fetch(buildUrl(path, options.params), {
    method, headers, body, credentials: "same-origin", signal: options.signal,
  });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const data: unknown = response.status === 204 ? null : isJson ? await response.json() : await response.text();
  if (!response.ok) throw new ApiError(response.status, errorMessage(data, response.status), data);
  return data as T;
}

/** Corps d'une action POST sans paramètre : un multipart vide est rejeté par Django (400). */
export function actionBody(data: Record<string, string | number | Blob> = {}): FormData {
  const fd = new FormData();
  Object.entries(data).forEach(([k, v]) => fd.append(k, v instanceof Blob ? v : String(v)));
  if (!Object.keys(data).length) fd.append("next", "/");
  return fd;
}
