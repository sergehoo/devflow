/**
 * Sauvegarde locale (IndexedDB) d'un enregistrement en cours ou non envoyé —
 * même base / même magasin que l'enregistreur historique (`devflow_recordings` /
 * `pending`, clé = id de réunion) : une capture interrompue dans l'une des deux
 * interfaces est retrouvée par l'autre. Contient uniquement l'audio (aucun jeton).
 */
export interface PendingSession {
  meetingId: string;
  blob: Blob;
  durationMs: number;
  savedAt: number;
  mimeType: string;
  sizeBytes: number;
}

const DB_NAME = "devflow_recordings";
const STORE = "pending";

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB indisponible"));
      return;
    }
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "meetingId" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function run<T>(mode: IDBTransactionMode, op: (store: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
  const db = await openDB();
  try {
    return await new Promise<T | undefined>((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const req = op(tx.objectStore(STORE));
      let result: T | undefined;
      if (req) req.onsuccess = () => { result = req.result; };
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

export async function savePendingSession(meetingId: number, blob: Blob, durationMs: number): Promise<void> {
  if (!blob.size) return;
  try {
    await run("readwrite", (s) => s.put({
      meetingId: String(meetingId), blob, durationMs, savedAt: Date.now(), mimeType: blob.type || "audio/webm", sizeBytes: blob.size,
    } satisfies PendingSession));
  } catch {
    /* best effort : la capture continue même sans sauvegarde locale */
  }
}

export async function loadPendingSession(meetingId: number): Promise<PendingSession | null> {
  try {
    const session = await run<PendingSession>("readonly", (s) => s.get(String(meetingId)) as IDBRequest<PendingSession>);
    return session && session.blob && session.blob.size > 0 ? session : null;
  } catch {
    return null;
  }
}

export async function clearPendingSession(meetingId: number): Promise<void> {
  try {
    await run("readwrite", (s) => s.delete(String(meetingId)));
  } catch {
    /* rien à nettoyer */
  }
}

/** « il y a 12 sec / 3 min / 2 h / 1 j » (bannière de récupération). */
export function savedAgo(savedAt: number, now = Date.now()): string {
  const sec = Math.round((now - savedAt) / 1000);
  if (sec < 60) return `il y a ${sec} sec`;
  if (sec < 3600) return `il y a ${Math.round(sec / 60)} min`;
  if (sec < 86400) return `il y a ${Math.round(sec / 3600)} h`;
  return `il y a ${Math.round(sec / 86400)} j`;
}
