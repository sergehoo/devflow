/**
 * Réunions & enregistrements — client des endpoints `/api/v1/meetings/…`
 * (vues Django existantes exécutées côté serveur : scoping, droits et règles restent dans Django).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api, getCookie } from "@/services/api";

export interface Choice { value: string; label: string }
export interface UserRef { id: number; name: string; email: string }
export interface ProjectRef { id: number; name: string }

export interface MeetingRow {
  id: number;
  title: string;
  status: string;
  status_label: string;
  meeting_type: string;
  type_label: string;
  scheduled_at: string;
  duration_minutes: number;
  duration_label: string;
  project: ProjectRef | null;
  organizer: string;
  location: string;
  series_id: number | null;
  is_past?: boolean;
  participants_count?: number;
  projects_count?: number;
}

export interface MeetingList {
  results: MeetingRow[];
  count: number;
  page: number;
  num_pages: number;
  type_choices: Choice[];
  status_choices: Choice[];
  current_project: ProjectRef | null;
}

export interface AgendaItem {
  id: number;
  position: number;
  title: string;
  description: string;
  description_html: string;
  notes: string;
  notes_html: string;
  owner: UserRef | null;
  duration_minutes: number;
  status: string;
  status_label: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ActionItem {
  id: number;
  title: string;
  description: string;
  owner: UserRef | null;
  due_date: string | null;
  status: string;
  status_label: string;
  priority: string;
  priority_label: string;
  converted_task_id: number | null;
  converted_at: string | null;
}

export interface Participation {
  user: UserRef;
  rsvp_status: string;
  rsvp_label: string;
  rsvp_note: string;
  rsvp_at: string | null;
  attendance_status: string;
  attendance_label: string;
  self_confirmed: boolean;
  attendance_marked_by: string;
  attendance_marked_at: string | null;
}

export interface ReviewField {
  name: string;
  label: string;
  type: string;
  required: boolean;
  disabled: boolean;
  help_text: string;
  value: unknown;
  max_length: number | null;
  min: number | null;
  max: number | null;
  choices?: Choice[];
}

export interface ReviewForm {
  id: number | null;
  prefix: string;
  project: ProjectRef | null;
  status_label: string;
  progress_pct: number;
  fields: ReviewField[];
}

export interface RecordingStatus {
  id: number;
  meeting_id: number;
  status: string;
  status_label: string;
  progress_percent: number;
  progress_label: string;
  is_terminal: boolean;
  is_final: boolean;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number;
  transcription_provider: string;
  summary_provider: string;
  error_message: string;
  speakers_count: number;
  recorded_by: string;
  has_summary: boolean;
}

export interface MeetingDetail extends MeetingRow {
  projects: ProjectRef[];
  sprint: ProjectRef | null;
  series: ProjectRef | null;
  organizer_user: UserRef | null;
  meeting_link: string;
  external_participants: string;
  participants_count: number;
  attachments_count: number;
  agenda_html: string;
  notes_html: string;
  decisions_html: string;
  blockers_html: string;
  next_steps_html: string;
  ai_summary: string;
  ai_used_provider: string;
  ai_extracted_at: string | null;
  created_by: string;
  created_at: string;
  updated_by: string;
  updated_at: string;
  agenda_items: AgendaItem[];
  agenda_status_choices: Choice[];
  action_items: ActionItem[];
  action_priority_choices: Choice[];
  /** Droit Django (RBAC `task.create` ou responsable du projet) de convertir une action en tâche. */
  can_convert_actions: boolean;
  participations: Participation[];
  my_participation: Participation | null;
  participations_stats: Partial<Record<"accepted" | "declined" | "tentative" | "pending" | "present" | "absent", number>>;
  can_mark_attendance: boolean;
  rsvp_choices: Choice[];
  attendance_choices: Choice[];
  reviews: { prefix: string; management: Record<string, string | number>; forms: ReviewForm[] } | null;
  structured_decisions: { id: number; title: string; status: string; status_label: string; category_label: string; decided_at: string }[];
  recordings: RecordingStatus[];
  max_upload_mb: number;
  downloads: { docx: string | null; pdf: string | null };
  legacy_url: string | null;
}

export interface Extraction {
  id: number;
  kind: string;
  kind_label: string;
  title: string;
  description: string;
  assignee_hint: string;
  due_date_hint: string;
  priority_hint: string;
  confidence: number;
  is_accepted: boolean;
  accepted_at: string | null;
}

export interface RecordingDetail extends RecordingStatus {
  meeting: { id: number; title: string; scheduled_at: string; internal_participants_count: number; has_external_participants: boolean };
  consent_acknowledged: boolean;
  original_filename: string;
  file_size_bytes: number;
  tokens_used: number;
  summary_markdown: string;
  transcript: string;
  segments: { speaker_label: string; speaker: string; start: number; end: number; text: string }[];
  segments_total: number;
  speakers: {
    label: string; display_name: string; total_duration_seconds: number; total_segments: number;
    mapped_participant_id: number | null; is_confirmed: boolean; sample_url: string | null;
  }[];
  participants: { id: string; full_name: string; email: string }[];
  all_mapped: boolean;
  decisions: Extraction[];
  actions: Extraction[];
  risks: Extraction[];
  project_suggestions: Extraction[];
  sprint_suggestions: Extraction[];
  milestone_suggestions: Extraction[];
  task_suggestions: Extraction[];
  mentions: Extraction[];
  /** Droits Django de création depuis les suggestions IA (RBAC `project.create` / `task.create`). */
  can_create_projects: boolean;
  can_create_tasks: boolean;
  audio_url: string | null;
  downloads: { docx: string | null; pdf: string | null };
}

export interface MeetingDashboard {
  month_stats: Partial<Record<"total" | "held" | "planned" | "cancelled", number>>;
  upcoming: MeetingRow[];
  recent: MeetingRow[];
  top_projects: { id: number; name: string; count: number }[];
  active_series: { id: number; name: string; recurrence_label: string }[];
  calendar: { day: number | null; date: string | null; count: number; is_today: boolean; is_weekend: boolean }[];
  speaking: { name: string; minutes: number }[];
  execution_rate: number;
  total_decisions_year: number;
  executed_decisions_year: number;
  top_discussed_projects: { title: string; count: number }[];
}

export interface Decision {
  id: number;
  title: string;
  description: string;
  category: string;
  category_label: string;
  status: string;
  status_label: string;
  decided_by: string;
  decided_at: string;
  executed_at: string | null;
  meeting: { id: number; title: string } | null;
  projects: ProjectRef[];
}

export interface SeriesRow {
  id: number; name: string; description: string; type_label: string; recurrence_label: string;
  default_projects_count: number; is_active: boolean;
}

export interface SeriesDetail {
  id: number; name: string; description: string; meeting_type: string; type_label: string; recurrence: string;
  recurrence_label: string; start_date: string; end_date: string | null; time_local: string; duration_minutes: number;
  location: string; meeting_link: string; is_active: boolean; organizer: string; default_participants: UserRef[];
  default_projects: ProjectRef[]; default_agenda: string; legacy_url: string | null;
  upcoming: { id: number; scheduled_at: string; status: string; status_label: string; title: string }[];
  past: { id: number; scheduled_at: string; status: string; status_label: string; title: string }[];
}

export interface ActionResult { messages?: string[]; ok?: boolean; [key: string]: unknown }

export const MEETINGS_KEY = ["meetings"] as const;

export type FormValue = string | number | boolean | Blob | null | undefined | (string | number)[];

/** Multipart : valeurs multiples répétées (cases cochées), booléen vrai → « on » ; jamais vide (Django rejette un multipart vide). */
export function toForm(data: Record<string, FormValue> = {}): FormData {
  const fd = new FormData();
  Object.entries(data).forEach(([key, value]) => {
    if (value === undefined || value === null || value === false) return;
    if (Array.isArray(value)) value.forEach((v) => fd.append(key, String(v)));
    else if (value instanceof Blob) fd.append(key, value);
    else fd.append(key, value === true ? "on" : String(value));
  });
  if (![...fd.keys()].length) fd.append("next", "/");
  return fd;
}

export const postAction = (path: string, data?: Record<string, FormValue>) =>
  api<ActionResult>(path, { method: "POST", body: toForm(data) });

/** Messages Django renvoyés par le pont (succès) ou repli. */
export const messagesOf = (r: ActionResult | undefined, fallback: string) => (r?.messages?.length ? r.messages : [fallback]);

export const useMeetings = (params: Record<string, string>) =>
  useQuery({
    queryKey: [...MEETINGS_KEY, "list", params],
    queryFn: ({ signal }) => api<MeetingList>("meetings/", { signal, params }),
    placeholderData: keepPreviousData,
  });

export const useMeeting = (id: number) =>
  useQuery({ queryKey: [...MEETINGS_KEY, id], queryFn: ({ signal }) => api<MeetingDetail>(`meetings/${id}/`, { signal }) });

export const useMeetingDashboard = () =>
  useQuery({ queryKey: [...MEETINGS_KEY, "dashboard"], queryFn: ({ signal }) => api<MeetingDashboard>("meetings/dashboard/", { signal }) });

export const useDecisions = (params: Record<string, string>) =>
  useQuery({
    queryKey: [...MEETINGS_KEY, "decisions", params],
    queryFn: ({ signal }) => api<{ results: Decision[]; count: number; status_choices: Choice[]; category_choices: Choice[] }>(
      "meetings/decisions/", { signal, params }),
    placeholderData: keepPreviousData,
  });

export const useSeriesList = (params: Record<string, string>) =>
  useQuery({
    queryKey: [...MEETINGS_KEY, "series", params],
    queryFn: ({ signal }) => api<{ results: SeriesRow[]; count: number; page: number; num_pages: number }>("meetings/series/", { signal, params }),
    placeholderData: keepPreviousData,
  });

export const useSeries = (id: number) =>
  useQuery({ queryKey: [...MEETINGS_KEY, "series", id], queryFn: ({ signal }) => api<SeriesDetail>(`meetings/series/${id}/`, { signal }) });

export const useRecording = (id: number, poll?: (data: RecordingDetail | undefined) => number | false) =>
  useQuery({
    queryKey: [...MEETINGS_KEY, "recording", id],
    queryFn: ({ signal }) => api<RecordingDetail>(`meetings/recordings/${id}/`, { signal }),
    refetchInterval: poll ? (q) => poll(q.state.data) : false,
  });

/** Polling du pipeline (équivalent du fragment htmx, toutes les 3 s ; 10 s en attente d'identification ; arrêt à l'état final). */
export const useRecordingStatus = (id: number | null, enabled = true) =>
  useQuery({
    queryKey: [...MEETINGS_KEY, "recording", id, "status"],
    queryFn: ({ signal }) => api<RecordingStatus>(`meetings/recordings/${id}/status/`, { signal }),
    enabled: enabled && id != null,
    refetchInterval: (q) => {
      const s = q.state.data;
      if (q.state.error instanceof ApiError && q.state.fetchFailureCount > 5) return false;
      if (!s) return 3000;
      if (s.is_final) return false;
      return s.status === "waiting_speaker_mapping" ? 10000 : 3000;
    },
  });

/** Action POST sur une réunion / un enregistrement + rafraîchissement des vues réunions. */
export function useMeetingAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ path, data }: { path: string; data?: Record<string, FormValue> }) => postAction(path, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: MEETINGS_KEY }),
  });
}

export interface UploadOptions {
  meetingId: number;
  file: Blob;
  durationSeconds: number;
  consent: boolean;
  recordingId?: number | null;
  onProgress?: (percent: number) => void;
}

/**
 * Envoi de l'audio : même endpoint et même format que l'enregistreur historique
 * (`recorder_widget.html`) — XHR pour la progression, pas de délai côté navigateur.
 */
export function uploadRecording({ meetingId, file, durationSeconds, consent, recordingId, onProgress }: UploadOptions) {
  return new Promise<{ recording_id: string; status: string }>((resolve, reject) => {
    const form = new FormData();
    if (recordingId) form.append("recording_id", String(recordingId));
    const named = file instanceof File && file.name ? file : new File([file], "recording.webm", { type: file.type || "audio/webm" });
    form.append("audio", named);
    form.append("duration_seconds", String(durationSeconds || 0));
    form.append("consent_acknowledged", String(consent));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/meetings/${meetingId}/recordings/upload/`);
    xhr.timeout = 0;
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    const token = getCookie("csrftoken");
    if (token) xhr.setRequestHeader("X-CSRFToken", token);
    xhr.upload.onprogress = (e) => { if (e.total) onProgress?.(Math.round((e.loaded / e.total) * 100)); };
    xhr.onload = () => {
      let data: { detail?: string; recording_id?: string; status?: string } = {};
      try { data = JSON.parse(xhr.responseText || "{}"); } catch { /* réponse non JSON */ }
      if (xhr.status >= 200 && xhr.status < 300 && data.recording_id) resolve(data as { recording_id: string; status: string });
      else reject(new Error(data.detail || xhr.statusText || `Erreur ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Erreur réseau — la connexion a été interrompue."));
    xhr.ontimeout = () => reject(new Error("Délai dépassé — vérifiez votre connexion."));
    xhr.onabort = () => reject(new Error("Upload annulé."));
    xhr.send(form);
  });
}

type Run = (path: string, data?: Record<string, FormValue>, after?: () => void, fallback?: string) => void;

/** Action POST → toasts (messages Django) + rafraîchissement des vues réunions. */
export function useRun(): [Run, boolean] {
  const action = useMeetingAction();
  const run: Run = (path, data, after, fallback = "Modifications enregistrées.") =>
    action.mutate({ path, data }, {
      onSuccess: (r) => { messagesOf(r, fallback).forEach((m) => toast.success(m)); after?.(); },
      onError: (e) => toast.error(e.message),
    });
  return [run, action.isPending];
}
