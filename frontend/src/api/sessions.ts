import { API_BASE_URL, apiClient } from "./client";
import { getToken } from "./auth";

export type Session = {
  id: string;
  title: string | null;
  created_at: string;
  scenario_preset_id?: string | null;
  scenario_label_ru?: string | null;
  scenario_goal?: string | null;
  speech_summary?: {
    wpm_avg: number | null;
    wpm_category: "below" | "normal" | "above" | string | null;
    pause_ratio: number | null;
    filler_count: number | null;
  } | null;
  voice_summary?: {
    pitch_cv: number | null;
    pitch_label: string | null;
    rms_cv: number | null;
    loudness_label: string | null;
  } | null;
};

export type SessionSummaryItem = {
  id: string;
  created_at: string;
  title: string | null;
  status: "ready" | "processing" | "error";
  scenario_preset_id?: string | null;
  scenario_goal?: string | null;
  scenario_label_ru?: string | null;
  summary: {
    wpm_avg: number | null;
    wpm_category: "below" | "normal" | "above" | null;
    pause_ratio: number | null;
    filler_count: number | null;
    filler_per_min?: number | null;
    redundancy_score?: number | null;
    top_starter?: string | null;
    weak_words_count?: number | null;
    pitch_cv: number | null;
    rms_cv: number | null;
    pitch_label?: string | null;
    loudness_label?: string | null;
    centering?: number | null;
    stability?: number | null;
    eye_contact?: number | null;
  };
};

export type MetricRating = "good" | "ok" | "bad" | "na";
export type MetricValue = { value: number | null; unit: string; label: string; rating: MetricRating; note: string };

export type SessionResults = {
  schema_version: 1;
  session_id: string;
  generated_at: string;
  status: "ready" | "error" | "processing";
  meta: Record<string, unknown>;
  delivery: {
    tempo: {
      wpm_avg: MetricValue;
      wpm_variability: MetricValue;
      wpm_normal_range: { min: number; max: number };
      wpm_category: "below" | "normal" | "above" | null;
      wpm_series: Array<{
        idx?: number;
        label?: string;
        speech_from_sec?: number;
        speech_to_sec?: number;
        words?: number;
        speech_sec?: number;
        timeline_spans?: Array<[number, number]>;
        seek_to_sec?: number | null;
        speech_t_start?: number;
        speech_t_end?: number;
        t_start?: number | null;
        t_end?: number | null;
        speech_active_sec?: number;
        wpm?: number | null;
        value?: number | null;
      }>;
      wpm_windows?: Array<{
        idx?: number;
        label?: string;
        speech_from_sec?: number;
        speech_to_sec?: number;
        words?: number;
        speech_sec?: number;
        timeline_spans?: Array<[number, number]>;
        seek_to_sec?: number | null;
        speech_t_start?: number;
        speech_t_end?: number;
        t_start?: number | null;
        t_end?: number | null;
        speech_active_sec?: number;
        wpm?: number | null;
        value?: number | null;
      }>;
      timecodes: Array<{ t: number; label: string; kind: "issue" | "good" | "info" }>;
    };
    pauses: {
      pause_ratio: MetricValue;
      pause_norm_percent?: { min: number; max: number };
      pause_category?: "low" | "normal" | "high" | null;
      pauses_stats?: { total_pause_sec?: number; count?: number; longest_pause_sec?: number };
      events: Array<{ start?: number; end?: number; dur?: number; t?: number; label?: string; kind?: string }>;
    };
  };
  word_choice: {
    fillers: { count: MetricValue; density: MetricValue; events: Array<{ phrase: string; start: number; end: number; t?: number; label?: string; kind?: string }> };
    templates: {
      sentence_starters: {
        items: Array<{ starter: string; ratio: number; count: number; timecodes: Array<{ t: number; label: string; kind: "issue" | "good" | "info" }> }>;
        rating: MetricRating;
        note: string;
      };
    };
    repetitions: {
      top_words: Array<{ word: string; count: number; timecodes: Array<{ t: number; label: string; kind: "issue" | "good" | "info" }> }>;
      top_phrases: Array<{ phrase: string; count: number; timecodes: Array<{ t: number; label: string; kind: "issue" | "good" | "info" }> }>;
      rating: MetricRating;
      note: string;
    };
    weak_words: {
      count: MetricValue;
      density_per_min?: MetricValue;
      items: Array<{ word: string; count: number; timecodes: Array<{ t: number; label: string; kind: "issue" | "good" | "info" }> }>;
    };
    conciseness: { redundancy_score: MetricValue };
  };
  voice: {
    pitch: { cv: MetricValue; label?: string | null; series: Array<{ t: number; f0?: number | null; value?: number }> };
    loudness: { rms_cv: MetricValue; label?: string | null; series: Array<{ t: number; rms?: number; value?: number }> };
  };
  visual: {
    centering: MetricValue;
    stability: MetricValue;
    eye_contact: MetricValue & { ratio?: number | null };
  };
  coaching: {
    strength: { title?: string; text: string; rating?: MetricRating | string };
    strength_v2?: {
      items: Array<{ title: string; text: string; evidence: string[]; metrics: string[]; timecode?: number | null }>;
      source?: "llm" | "fallback" | string;
      fallback_reason?: string | null;
      request_id?: string | null;
      llm_latency_ms?: number | null;
    };
    growth: { title?: string; bullets: string[]; rating?: MetricRating | string };
    growth_v2?: {
      items: Array<{ title: string; text: string; why_for_scenario: string; action: string; evidence: string[]; metrics: string[]; timecode?: number | null }>;
      source?: "llm" | "fallback" | string;
      fallback_reason?: string | null;
      request_id?: string | null;
      llm_latency_ms?: number | null;
    };
    questions: {
      title?: string;
      items: string[];
      source?: "llm" | "fallback" | string;
      fallback_reason?: string | null;
      request_id?: string | null;
      llm_latency_ms?: number | null;
    };
    summary: {
      title?: string;
      bullets: string[];
      keywords?: string[];
      source?: "llm" | "fallback" | string;
      fallback_reason?: string | null;
      request_id?: string | null;
      llm_latency_ms?: number | null;
    };
    keywords?: {
      title?: string;
      items: string[];
      source?: "llm" | "fallback" | string;
      fallback_reason?: string | null;
      request_id?: string | null;
      llm_latency_ms?: number | null;
    };
    goal?: {
      status?: "achieved" | "partial" | "not_achieved" | string;
      achieved: "yes" | "partial" | "no";
      summary: string;
      criteria?: Array<{ key: string; title: string; score: number; verdict: string; metrics: string[]; explanation?: string }>;
      reasons: Array<{ metric: string; value?: number | null; norm?: string; text?: string; verdict?: string; why?: string }>;
      actions: string[];
      source: "llm" | "fallback" | string;
      fallback_reason: string | null;
      request_id?: string | null;
      llm_latency_ms?: number | null;
    };
  };
};

export type SessionScenarioPayload = {
  mode: "preset" | "free_text";
  preset_id?: string;
  structured?: {
    audience: string;
    tone: string;
    goal: string;
  };
  free_text?: string;
  autopick?: boolean;
};

export type SessionScenarioResponse = {
  scenario_mode: "preset" | "free_text";
  preset_id: string | null;
  structured: SessionScenarioPayload["structured"] | null;
  free_text: string | null;
  autopick: boolean;
  profile: Record<string, unknown> | null;
};

export type MediaItem = {
  id: string;
  session_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  duration_seconds: number | null;
  sample_rate?: number | null;
  channels?: number | null;
  processed_audio_path?: string | null;
  storage_path: string;
  created_at: string;
};

export type SessionStatus = {
  session_id: string;
  status: "queued" | "processing" | "ready" | "error";
  step: string | null;
  progress: number | null;
  error_message: string | null;
  updated_at: string | null;
};

export type TranscriptWord = {
  token: string;
  start: number;
  end: number;
  confidence: number | null;
  low_confidence: boolean;
};


export type SegmentRewriteShort = { kind: "short"; text: string };
export type SegmentRewriteBullets = { kind: "bullets"; bullets: string[] };

export type SessionSegment = {
  id: string;
  idx: number;
  start_sec: number;
  end_sec: number;
  text: string;
  rewrites: {
    short?: SegmentRewriteShort | null;
    bullets?: SegmentRewriteBullets | null;
  };
};


export type SessionComment = {
  session_id: string;
  text: string | null;
  updated_at: string | null;
};

export type SessionTranscript = {
  session_id: string;
  language: "ru" | "en" | null | string;
  text: string | null;
  words: TranscriptWord[];
  updated_at: string | null;
};

export const fetchSessions = async () => {
  const response = await apiClient.get<Session[]>("/sessions");
  return response.data;
};

export const fetchSessionsSummary = async () => {
  const response = await apiClient.get<SessionSummaryItem[]>("/sessions/summary");
  return response.data;
};

export const createSession = async (title?: string) => {
  const response = await apiClient.post<Session>("/sessions", { title: title || null });
  return response.data;
};

export const fetchSession = async (sessionId: string) => {
  const response = await apiClient.get<Session>(`/sessions/${sessionId}`);
  return response.data;
};

export const fetchSessionScenario = async (sessionId: string) =>
  (await apiClient.get<SessionScenarioResponse>(`/sessions/${sessionId}/scenario`)).data;

export const putSessionScenario = async (sessionId: string, payload: SessionScenarioPayload) =>
  (await apiClient.put<SessionScenarioResponse>(`/sessions/${sessionId}/scenario`, payload)).data;

export const fetchSessionMedia = async (sessionId: string) => {
  const response = await apiClient.get<MediaItem[]>(`/sessions/${sessionId}/media`);
  return response.data;
};

export const uploadSessionMedia = async (sessionId: string, file: File, onProgress?: (percent: number) => void) => {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiClient.post<MediaItem>(`/sessions/${sessionId}/media`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (event) => {
      if (!event.total) return;
      onProgress?.(Math.round((event.loaded / event.total) * 100));
    },
  });
  return response.data;
};

export const uploadSessionMediaByUrl = async (
  sessionId: string,
  url: string,
  onProgress?: (state: { percent: number | null; downloadedBytes: number; totalBytes: number | null }) => void,
) => {
  const token = getToken();
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/media-url`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ url }),
  });

  const totalBytesHeader = response.headers.get("content-length");
  const totalBytes = totalBytesHeader ? Number(totalBytesHeader) : null;

  if (!response.ok) {
    let detail = "";
    try {
      const data = await response.json();
      detail = data?.detail || "";
    } catch {
      detail = "";
    }
    const error = new Error(detail || "upload by url failed");
    (error as Error & { status?: number }).status = response.status;
    throw error;
  }

  if (!response.body) {
    return (await response.json()) as MediaItem;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let downloadedBytes = 0;
  let payloadText = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    downloadedBytes += value.length;
    onProgress?.({
      percent: totalBytes ? Math.round((downloadedBytes / totalBytes) * 100) : null,
      downloadedBytes,
      totalBytes,
    });
    payloadText += decoder.decode(value, { stream: true });
  }
  payloadText += decoder.decode();
  return JSON.parse(payloadText) as MediaItem;
};

export const startSessionAnalysis = async (sessionId: string) => (await apiClient.post<SessionStatus>(`/sessions/${sessionId}/start`)).data;
export const fetchSessionStatus = async (sessionId: string) => (await apiClient.get<SessionStatus>(`/sessions/${sessionId}/status`)).data;
export const fetchSessionResults = async (sessionId: string) => (await apiClient.get<SessionResults>(`/sessions/${sessionId}/results`)).data;
export const reanalyzeSession = async (sessionId: string) => (await apiClient.post<SessionStatus>(`/sessions/${sessionId}/reanalyze`)).data;
export const deleteSession = async (sessionId: string) => {
  await apiClient.delete(`/sessions/${sessionId}`);
};

export const getMediaPlaybackUrl = (media: MediaItem) => {
  const token = getToken();
  const params = new URLSearchParams();
  if (token) params.set("token", token);
  const query = params.toString();
  return `${API_BASE_URL}/sessions/media/${media.id}/stream${query ? `?${query}` : ""}`;
};

export const fetchSessionTranscript = async (sessionId: string) => (await apiClient.get<SessionTranscript>(`/sessions/${sessionId}/transcript`)).data;
export const patchSessionTranscript = async (sessionId: string, payload: { text: string; language?: string | null }) =>
  (await apiClient.patch<SessionTranscript>(`/sessions/${sessionId}/transcript`, payload)).data;


export const fetchSessionSegments = async (sessionId: string) =>
  (await apiClient.get<SessionSegment[]>(`/sessions/${sessionId}/segments`)).data;

export const rewriteSessionSegment = async (sessionId: string, segmentId: string, kind: "short" | "bullets") =>
  (await apiClient.post<SegmentRewriteShort | SegmentRewriteBullets>(`/sessions/${sessionId}/segments/${segmentId}/rewrite`, { kind })).data;


export const fetchSessionComment = async (sessionId: string) =>
  (await apiClient.get<SessionComment>(`/sessions/${sessionId}/comment`)).data;

export const putSessionComment = async (sessionId: string, payload: { text: string | null }) =>
  (await apiClient.put<SessionComment>(`/sessions/${sessionId}/comment`, payload)).data;
