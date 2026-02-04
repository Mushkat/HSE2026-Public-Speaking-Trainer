import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AxiosError } from "axios";

import {
  fetchSession,
  fetchSessionMedia,
  MediaItem,
  Session,
  uploadSessionMedia,
} from "../api/sessions";

const SessionDetailsPage = () => {
  const { sessionId } = useParams();
  const [session, setSession] = useState<Session | null>(null);
  const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const formattedMediaItems = useMemo(() => {
    return mediaItems.map((item) => ({
      ...item,
      createdLabel: new Date(item.created_at).toLocaleString(),
      sizeLabel: formatBytes(item.size_bytes),
    }));
  }, [mediaItems]);

  useEffect(() => {
    const loadSession = async () => {
      if (!sessionId) {
        setError("Missing session id.");
        setLoading(false);
        return;
      }
      try {
        const [data, media] = await Promise.all([
          fetchSession(sessionId),
          fetchSessionMedia(sessionId),
        ]);
        setSession(data);
        setMediaItems(media);
      } catch (err) {
        setError("Unable to load this session.");
      } finally {
        setLoading(false);
      }
    };

    loadSession();
  }, [sessionId]);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    setSelectedFile(file);
    setUploadError("");
    setUploadProgress(0);
  };

  const handleUpload = async () => {
    if (!sessionId || !selectedFile) {
      setUploadError("Select a file before uploading.");
      return;
    }
    setUploading(true);
    setUploadError("");
    setUploadProgress(0);
    try {
      const uploaded = await uploadSessionMedia(sessionId, selectedFile, setUploadProgress);
      setMediaItems((prev) => [uploaded, ...prev]);
      setSelectedFile(null);
    } catch (err) {
      setUploadError(getUploadErrorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h1>Session details</h1>
          <p className="muted">Review metadata before uploading recordings.</p>
        </div>
        <Link to="/sessions" className="button-secondary">
          Back to sessions
        </Link>
      </div>
      {loading ? (
        <p className="muted">Loading session...</p>
      ) : error ? (
        <div className="error">{error}</div>
      ) : session ? (
        <>
          <div className="session-detail">
            <div>
              <span className="label">Session ID</span>
              <div className="value">{session.id}</div>
            </div>
            <div>
              <span className="label">Title</span>
              <div className="value">{session.title || "Untitled session"}</div>
            </div>
            <div>
              <span className="label">Created at</span>
              <div className="value">{new Date(session.created_at).toLocaleString()}</div>
            </div>
          </div>

          <div className="upload-panel">
            <div>
              <h2>Upload media</h2>
              <p className="muted">
                Supported formats: mp4, mov, webm, mp3, wav (max 500MB).
              </p>
            </div>
            <div className="upload-controls">
              <input
                type="file"
                onChange={handleFileChange}
                accept=".mp4,.mov,.webm,.mp3,.wav"
              />
              <button
                className="primary"
                onClick={handleUpload}
                disabled={!selectedFile || uploading}
              >
                {uploading ? "Uploading..." : "Upload"}
              </button>
            </div>
            {selectedFile ? (
              <div className="upload-meta">
                <span>{selectedFile.name}</span>
                <span>{formatBytes(selectedFile.size)}</span>
              </div>
            ) : null}
            {uploading ? (
              <div className="upload-progress">
                <span>Uploading...</span>
                <span>{uploadProgress}%</span>
              </div>
            ) : null}
            {uploadError ? <div className="error">{uploadError}</div> : null}
          </div>

          <div className="media-panel">
            <div className="media-header">
              <h2>Attached media</h2>
              <span className="muted">{mediaItems.length} file(s)</span>
            </div>
            {formattedMediaItems.length === 0 ? (
              <p className="muted">No uploads yet.</p>
            ) : (
              <ul className="media-list">
                {formattedMediaItems.map((item) => (
                  <li key={item.id} className="media-item">
                    <div>
                      <div className="media-name">{item.filename}</div>
                      <div className="muted">
                        {item.sizeLabel} • {item.mime_type}
                      </div>
                    </div>
                    <div className="media-date">{item.createdLabel}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
};

const formatBytes = (bytes: number) => {
  if (bytes === 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, index);
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
};

const getUploadErrorMessage = (error: unknown) => {
  if (error && (error as AxiosError).isAxiosError) {
    const axiosError = error as AxiosError<{ detail?: string }>;
    if (axiosError.response?.status === 401) {
      return "Your session expired. Please log in again.";
    }
    if (axiosError.response?.status === 404) {
      return "Session not found or you do not have access.";
    }
    if (axiosError.response?.status === 413) {
      return "File too large. Max size is 500MB.";
    }
    if (axiosError.response?.status === 415) {
      return "Unsupported file format. Use mp4, mov, webm, mp3, or wav.";
    }
    return axiosError.response?.data?.detail || "Upload failed. Please try again.";
  }
  return "Upload failed. Please try again.";
};

export default SessionDetailsPage;
