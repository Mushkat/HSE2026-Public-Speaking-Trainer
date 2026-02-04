import { apiClient } from "./client";

export type Session = {
  id: string;
  title: string | null;
  created_at: string;
};

export type MediaItem = {
  id: string;
  session_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  duration_seconds: number | null;
  storage_path: string;
  created_at: string;
};

export const fetchSessions = async () => {
  const response = await apiClient.get<Session[]>("/sessions");
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

export const fetchSessionMedia = async (sessionId: string) => {
  const response = await apiClient.get<MediaItem[]>(`/sessions/${sessionId}/media`);
  return response.data;
};

export const uploadSessionMedia = async (
  sessionId: string,
  file: File,
  onProgress?: (percent: number) => void,
) => {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiClient.post<MediaItem>(`/sessions/${sessionId}/media`, formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
    onUploadProgress: (event) => {
      if (!event.total) {
        return;
      }
      const percent = Math.round((event.loaded / event.total) * 100);
      onProgress?.(percent);
    },
  });
  return response.data;
};
