import { ChangeEvent, DragEvent, useMemo, useRef, useState } from "react";
import { AxiosError } from "axios";
import { useNavigate } from "react-router-dom";

import {
  createSession,
  fetchSessionScenario,
  putSessionScenario,
  startSessionAnalysis,
  uploadSessionMedia,
  uploadSessionMediaByUrl,
} from "../api/sessions";
import { t } from "../i18n";
import "./PracticePage.css";
import Alert from "../components/ui/Alert";
import Button from "../components/ui/Button";
import { Card, CardContent, CardHeader } from "../components/ui/Card";
import Input from "../components/ui/Input";
import ProgressBar from "../components/ui/ProgressBar";
import Textarea from "../components/ui/Textarea";
import { useToast } from "../components/ui/Toast";
import { formatBytes } from "../utils/format";

const PRESETS = [
  "scientific_lecture",
  "conference_talk",
  "pitch_sales",
  "interview_self_intro",
  "storytelling",
  "kids_lesson",
] as const;

const PracticePage = () => {
  const navigate = useNavigate();
  const { pushToast } = useToast();

  const [title, setTitle] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [scenarioTab, setScenarioTab] = useState<"preset" | "free_text">("preset");
  const [scenarioPresetId, setScenarioPresetId] = useState<string>("conference_talk");
  const [scenarioAudience, setScenarioAudience] = useState("general");
  const [scenarioGoal, setScenarioGoal] = useState("inform");
  const [scenarioTone, setScenarioTone] = useState("friendly");
  const [scenarioFreeText, setScenarioFreeText] = useState("");
  const [scenarioAutopick, setScenarioAutopick] = useState(true);
  const [scenarioSaving, setScenarioSaving] = useState(false);
  const [scenarioSaved, setScenarioSaved] = useState(false);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploaded, setUploaded] = useState(false);
  const [starting, setStarting] = useState(false);
  const [uploadMode, setUploadMode] = useState<"file" | "url">("file");
  const [mediaUrl, setMediaUrl] = useState("");
  const [downloadedMb, setDownloadedMb] = useState(0);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const canUpload = useMemo(
    () => Boolean(sessionId && scenarioSaved && (uploadMode === "file" ? selectedFile : mediaUrl.trim()) && !uploading && !uploaded),
    [sessionId, scenarioSaved, selectedFile, mediaUrl, uploadMode, uploading, uploaded],
  );

  const handleCreateSession = async () => {
    setCreating(true);
    setError("");
    try {
      const session = await createSession(title.trim() || undefined);
      setSessionId(session.id);
      const existingScenario = await fetchSessionScenario(session.id);
      if (existingScenario.profile) {
        setScenarioSaved(true);
      }
      pushToast(t("practice.created"), "success");
    } catch {
      setError(t("practice.createError"));
    } finally {
      setCreating(false);
    }
  };

  const handleSaveScenario = async () => {
    if (!sessionId) return;
    setScenarioSaving(true);
    setError("");
    try {
      if (scenarioTab === "preset") {
        await putSessionScenario(sessionId, {
          mode: "preset",
          preset_id: scenarioPresetId,
          structured: {
            audience: scenarioAudience,
            tone: scenarioTone,
            goal: scenarioGoal,
          },
        });
      } else {
        await putSessionScenario(sessionId, {
          mode: "free_text",
          free_text: scenarioFreeText,
          autopick: scenarioAutopick,
        });
      }
      setScenarioSaved(true);
      pushToast(t("practice.scenarioSaved"), "success");
    } catch {
      setError(t("practice.scenarioSaveError"));
    } finally {
      setScenarioSaving(false);
    }
  };

  const handleSkipScenario = async () => {
    if (!sessionId) return;
    setScenarioSaving(true);
    setError("");
    try {
      await putSessionScenario(sessionId, {
        mode: "preset",
        preset_id: "conference_talk",
        structured: { audience: "general", tone: "friendly", goal: "inform" },
        autopick: false,
      });
      setScenarioSaved(true);
      pushToast(t("practice.scenarioSaved"), "success");
    } catch {
      setError(t("practice.scenarioSaveError"));
    } finally {
      setScenarioSaving(false);
    }
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    setSelectedFile(file);
    setError("");
    setUploadProgress(0);
  };

  const handleClearSelectedFile = () => {
    setSelectedFile(null);
    setUploadProgress(0);
    setError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragOver(false);
    const file = event.dataTransfer.files?.[0] || null;
    setSelectedFile(file);
    setError("");
    setUploadProgress(0);
  };

  const handleUpload = async () => {
    if (!sessionId || !scenarioSaved) {
      setError(t("practice.scenarioRequired"));
      return;
    }
    if (uploadMode === "file" && !selectedFile) {
      setError(t("practice.chooseFileFirst"));
      return;
    }
    if (uploadMode === "url" && !mediaUrl.trim()) {
      setError(t("practice.uploadUrlLabel"));
      return;
    }

    setUploading(true);
    setError("");
    setUploadProgress(0);
    try {
      if (uploadMode === "file" && selectedFile) {
        await uploadSessionMedia(sessionId, selectedFile, setUploadProgress);
      } else {
        await uploadSessionMediaByUrl(sessionId, mediaUrl.trim(), ({ percent, downloadedBytes }) => {
          setUploadProgress(percent ?? 0);
          setDownloadedMb(Number((downloadedBytes / (1024 * 1024)).toFixed(2)));
        });
      }
      setUploaded(true);
      pushToast(t("practice.uploaded"), "success");
    } catch (uploadError) {
      setError(getUploadErrorMessage(uploadError));
    } finally {
      setUploading(false);
    }
  };

  const handleStartAnalysis = async () => {
    if (!sessionId) return;
    setStarting(true);
    setError("");
    try {
      await startSessionAnalysis(sessionId);
      pushToast(t("practice.started"), "info");
      navigate(`/sessions/${sessionId}`);
    } catch (startError) {
      setError(getAnalysisErrorMessage(startError));
    } finally {
      setStarting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div>
          <h2>{t("practice.title")}</h2>
          <p className="ui-muted">{t("practice.subtitle")}</p>
        </div>
      </CardHeader>
      <CardContent>
        <Input
          label={t("practice.titleLabel")}
          placeholder={t("practice.titlePlaceholder")}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          disabled={Boolean(sessionId)}
        />

        <div className="ui-row">
          <Button onClick={handleCreateSession} loading={creating} disabled={Boolean(sessionId)}>
            {t("common.actions.createPractice")}
          </Button>
          {sessionId ? <Alert tone="success">{t("practice.created")}</Alert> : null}
        </div>

        {sessionId ? (
          <div className="practice-upload">
            <div className="practice-scenario-card">
              <h3>{t("practice.scenarioTitle")}</h3>
              <div className="practice-upload-toggle" role="tablist" aria-label={t("practice.scenarioTitle")}>
                <button type="button" className={`practice-toggle-btn ${scenarioTab === "preset" ? "is-active" : ""}`} onClick={() => setScenarioTab("preset")}>{t("practice.scenarioPickTab")}</button>
                <button type="button" className={`practice-toggle-btn ${scenarioTab === "free_text" ? "is-active" : ""}`} onClick={() => setScenarioTab("free_text")}>{t("practice.scenarioDescribeTab")}</button>
              </div>

              {scenarioTab === "preset" ? (
                <div className="practice-scenario-grid">
                  <label><span>{t("practice.scenarioPreset")}</span><select value={scenarioPresetId} onChange={(e) => setScenarioPresetId(e.target.value)}>{PRESETS.map((preset) => <option key={preset} value={preset}>{t(`scenario.presets.${preset}`)}</option>)}</select></label>
                  <label><span>{t("practice.scenarioAudience")}</span><select value={scenarioAudience} onChange={(e) => setScenarioAudience(e.target.value)}>{["colleagues", "clients", "students", "kids", "general"].map((item) => <option key={item} value={item}>{t(`scenario.audience.${item}`)}</option>)}</select></label>
                  <label><span>{t("practice.scenarioGoal")}</span><select value={scenarioGoal} onChange={(e) => setScenarioGoal(e.target.value)}>{["inform", "teach", "persuade", "sell", "inspire", "entertain"].map((item) => <option key={item} value={item}>{t(`scenario.goal.${item}`)}</option>)}</select></label>
                  <label><span>{t("practice.scenarioTone")}</span><select value={scenarioTone} onChange={(e) => setScenarioTone(e.target.value)}>{["calm", "energetic", "friendly", "formal"].map((item) => <option key={item} value={item}>{t(`scenario.tone.${item}`)}</option>)}</select></label>
                </div>
              ) : (
                <div className="practice-scenario-free">
                  <h4>{t("practice.scenarioFreeTitle")}</h4>
                  <p className="ui-muted practice-scenario-helper">{t("practice.scenarioFreeHelper")}</p>
                  <Textarea value={scenarioFreeText} onChange={(event) => setScenarioFreeText(event.target.value)} />
                  <label className="practice-scenario-checkbox"><input type="checkbox" checked={scenarioAutopick} onChange={(e) => setScenarioAutopick(e.target.checked)} />{t("practice.scenarioAutopick")}</label>
                </div>
              )}

              <div className="ui-row">
                <Button onClick={handleSaveScenario} loading={scenarioSaving}>{t("practice.scenarioSave")}</Button>
                <Button variant="ghost" onClick={handleSkipScenario} loading={scenarioSaving}>{t("practice.scenarioSkip")}</Button>
                {scenarioSaved ? <span className="ui-muted">{t("practice.scenarioSaved")}</span> : null}
              </div>
            </div>

            <div className="practice-upload-toggle" role="tablist" aria-label={t("practice.title")}>
              <button type="button" className={`practice-toggle-btn ${uploadMode === "file" ? "is-active" : ""}`} onClick={() => setUploadMode("file")}>{t("practice.uploadModeFile")}</button>
              <button type="button" className={`practice-toggle-btn ${uploadMode === "url" ? "is-active" : ""}`} onClick={() => setUploadMode("url")}>{t("practice.uploadModeUrl")}</button>
            </div>

            {uploadMode === "file" ? (
              <>
                <label className={`practice-dropzone ${isDragOver ? "practice-dropzone--active" : ""}`} onDragOver={(event) => { event.preventDefault(); setIsDragOver(true); }} onDragLeave={() => setIsDragOver(false)} onDrop={handleDrop}>
                  <input ref={fileInputRef} type="file" accept=".mp4,.mov,.webm,.mp3,.wav" onChange={handleFileChange} className="practice-file-input" disabled={uploading || uploaded || !scenarioSaved} />
                  <strong>{t("practice.dropTitle")}</strong>
                  <span className="ui-muted">{scenarioSaved ? t("practice.dropHint") : t("practice.scenarioRequired")}</span>
                </label>
                {selectedFile ? (
                  <div className="practice-file-meta">
                    <div className="practice-file-meta__details"><span>{selectedFile.name}</span><span className="ui-muted">{formatBytes(selectedFile.size)}</span></div>
                    <Button variant="danger" type="button" onClick={handleClearSelectedFile} disabled={uploading}>{t("practice.removeFile")}</Button>
                  </div>
                ) : <div className="ui-muted">{t("common.labels.fileNotSelected")}</div>}
              </>
            ) : (
              <div className="practice-url-upload">
                <Input label={t("practice.uploadUrlLabel")} placeholder={t("practice.uploadUrlPlaceholder")} value={mediaUrl} onChange={(event) => setMediaUrl(event.target.value)} disabled={uploading || uploaded || !scenarioSaved} />
                <p className="ui-muted">{t("practice.uploadUrlHint")}</p>
              </div>
            )}

            {!scenarioSaved ? <Alert tone="info">{t("practice.scenarioRequired")}</Alert> : null}
            {uploading ? <ProgressBar value={uploadProgress} /> : null}
            {uploading && uploadMode === "url" && uploadProgress === 0 ? <div className="ui-muted">{t("practice.uploadByUrlProgressUnknown", { value: downloadedMb })}</div> : null}
            {uploaded ? <Alert tone="success">{t("practice.uploadComplete")}</Alert> : null}

            <div className="ui-row">
              <Button onClick={handleUpload} disabled={!canUpload} loading={uploading}>{uploadMode === "file" ? t("common.actions.upload") : t("practice.uploadByUrlButton")}</Button>
              <Button onClick={handleStartAnalysis} disabled={!uploaded} loading={starting}>{t("common.actions.startAnalysis")}</Button>
            </div>
          </div>
        ) : (
          <Alert tone="info">{t("practice.uploadFirstInfo")}</Alert>
        )}

        {error ? <Alert tone="danger">{error}</Alert> : null}
      </CardContent>
    </Card>
  );
};

const getUploadErrorMessage = (error: unknown) => {
  if (error && (error as AxiosError).isAxiosError) {
    const axiosError = error as AxiosError<{ detail?: string }>;
    if (axiosError.response?.status === 401) return t("errors.sessionExpired");
    if (axiosError.response?.status === 404) return t("practice.uploadNotFound");
    if (axiosError.response?.status === 409) return axiosError.response?.data?.detail || t("practice.uploadConflict");
    if (axiosError.response?.status === 413) return t("practice.uploadTooLarge");
    if (axiosError.response?.status === 415) return t("practice.uploadUnsupported");
    return axiosError.response?.data?.detail || t("practice.uploadGeneric");
  }
  return t("practice.uploadGeneric");
};

const getAnalysisErrorMessage = (error: unknown) => {
  if (error && (error as AxiosError).isAxiosError) {
    const axiosError = error as AxiosError<{ detail?: string }>;
    return axiosError.response?.data?.detail || t("practice.analysisStartError");
  }
  return t("practice.analysisStartError");
};

export default PracticePage;
