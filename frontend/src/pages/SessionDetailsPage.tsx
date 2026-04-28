import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AxiosError } from "axios";

import {
  deleteSession,
  fetchSession,
  fetchSessionMedia,
  fetchSessionStatus,
  fetchSessionTranscript,
  fetchSessionSegments,
  patchSessionTranscript,
  rewriteSessionSegment,
  fetchSessionResults,
  MediaItem,
  Session,
  SessionStatus,
  SessionTranscript,
  SessionSegment,
  SessionResults,
  reanalyzeSession,
  startSessionAnalysis,
  uploadSessionMedia,
  getMediaPlaybackUrl,
  fetchSessionComment,
  putSessionComment,
  fetchSessionScenario,
} from "../api/sessions";
import AnalysisProgress from "../components/analysis/AnalysisProgress";
import ErrorState from "../components/state/ErrorState";
import Alert from "../components/ui/Alert";
import Button from "../components/ui/Button";
import { Card, CardContent, CardHeader } from "../components/ui/Card";
import Dialog from "../components/ui/Dialog";
import ProgressBar from "../components/ui/ProgressBar";
import Skeleton from "../components/ui/Skeleton";
import { Tabs } from "../components/ui/Tabs";
import Textarea from "../components/ui/Textarea";
import { useLLMStatus } from "../components/layout/LLMStatusContext";
import { t } from "../i18n";
import { formatBytes, formatMetricLabel, formatPercent, formatPerMin, formatRange } from "../utils/format";
import { formatTime } from "../utils/time";
import "./SessionDetailsPage.css";

type InsightTab = "coaching" | "analytics";
type TimecodeChip = {
  t: number;
  label?: string;
  kind?: "issue" | "good" | "info" | string;
};

type WordChoiceChipSource = {
  starter?: string;
  word?: string;
  phrase?: string;
  count?: number;
  ratio?: number;
  timecodes?: TimecodeChip[];
};

type CompactTile = {
  title: string;
  main: string;
  lines: string[];
  tooltipLines?: string[];
};

const getEventTime = (event: { t?: number; start?: number | null }) => {
  if (typeof event.t === "number" && Number.isFinite(event.t)) return event.t;
  if (typeof event.start === "number" && Number.isFinite(event.start)) return event.start;
  return null;
};

const getTimecodeLabel = (timecode: TimecodeChip, fallbackLabel?: string) => {
  const prefix = formatTime(timecode.t);
  const suffix = (timecode.label || fallbackLabel || "").trim();
  if (suffix.startsWith(prefix)) {
    return suffix;
  }
  return suffix ? `${prefix} ${suffix}` : prefix;
};

const metricValueWithNorm = (metric: string, value: number | null, norm?: string) => {
  if (metric === "wpm") {
    return `Темп: ${typeof value === "number" ? Math.round(value) : "—"} слов/мин${norm ? ` при норме ${norm}` : ""}`;
  }
  if (metric === "pause_percent") {
    return `Паузы: ${formatPercent(value)}${norm ? ` при норме ${norm}` : ""}`;
  }
  if (metric === "fillers_per_min") {
    return `Паразиты: ${formatPerMin(value)}${norm ? ` при норме ${norm}` : ""}`;
  }
  if (metric === "redundancy_percent") {
    return `Избыточность: ${formatPercent(value)}${norm ? ` при норме ${norm}` : ""}`;
  }
  if (metric === "pitch_cv") {
    return `Интонация: ${typeof value === "number" ? value.toFixed(2) : "—"}${norm ? ` при норме ${norm}` : ""}`;
  }
  if (metric === "eye_contact") {
    return `Контакт: ${typeof value === "number" ? value.toFixed(1) : "—"}/5${norm ? ` при норме ${norm}` : ""}`;
  }
  return `${formatMetricLabel(metric)}: ${typeof value === "number" ? value : "—"}${norm ? ` при норме ${norm}` : ""}`;
};

const metricImpactText = (metric: string, value: number | null, norm?: string) => {
  const [minRaw, maxRaw] = String(norm || "").split(/[–-]/);
  const min = Number(minRaw);
  const max = Number(maxRaw);
  const below = typeof value === "number" && Number.isFinite(min) ? value < min : false;
  const above = typeof value === "number" && Number.isFinite(max) ? value > max : false;
  if (metric === "wpm") {
    if (below) return "Речь звучит медленнее, чем ожидается: часть аудитории теряет динамику и хуже держит внимание на тезисе.";
    if (above) return "Речь звучит слишком быстро: слушателю сложнее уловить смысл и запомнить ключевые выводы.";
  }
  if (metric === "pause_percent") {
    if (above) return "Паузы разбивают мысль: связность снижается и выступление кажется менее уверенным.";
    if (below) return "Паузы почти отсутствуют: речь воспринимается плотной и утомляет.";
  }
  if (metric === "fillers_per_min" && above) return "Слова-паразиты создают ощущение неуверенности и отвлекают от смысла.";
  if (metric === "redundancy_percent" && above) return "Повторы и лишние слова удлиняют речь и снижают ясность тезисов.";
  if (metric === "pitch_cv" && below) return "Интонация звучит ровно: важные места не выделяются и хуже запоминаются.";
  if (metric === "eye_contact" && below) return "Контакт с аудиторией слабее: доверие и вовлечённость ниже.";
  return "Метрика близка к норме, но эта зона всё ещё влияет на итоговую убедительность выступления.";
};

const formatVoiceText = (value: string | null | undefined) => {
  const base = String(value || "")
    .replace(/pitch\s*cv/gi, "коэффициент вариативности интонации")
    .replace(/rms\s*cv/gi, "коэффициент вариативности громкости")
    .replace(/\s+/g, " ")
    .trim();
  if (!base) return "—";
  return base.charAt(0).toUpperCase() + base.slice(1);
};

const SessionDetailsPage = () => {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [session, setSession] = useState<Session | null>(null);
  const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
  const [hasMedia, setHasMedia] = useState(false);
  const [statusInfo, setStatusInfo] = useState<SessionStatus | null>(null);
  const [transcript, setTranscript] = useState<SessionTranscript | null>(null);
  const [segments, setSegments] = useState<SessionSegment[]>([]);
  const [segmentRewriteLoading, setSegmentRewriteLoading] = useState<Record<string, "short" | "bullets" | null>>({});
  const [results, setResults] = useState<SessionResults | null>(null);
  const [scenarioProfile, setScenarioProfile] = useState<Record<string, any> | null>(null);
  const [transcriptText, setTranscriptText] = useState("");
  const [transcriptError, setTranscriptError] = useState("");
  const [savingTranscript, setSavingTranscript] = useState(false);
  const [copyStatus, setCopyStatus] = useState<"idle" | "success" | "error">("idle");

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");

  const [analysisError, setAnalysisError] = useState("");
  const [startingAnalysis, setStartingAnalysis] = useState(false);

  const [deleting, setDeleting] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const [comment, setComment] = useState("");
  const [savedComment, setSavedComment] = useState("");
  const [commentStatus, setCommentStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [insightTab, setInsightTab] = useState<InsightTab>("coaching");
  const [showAllStrength, setShowAllStrength] = useState(false);
  const [showAllGrowth, setShowAllGrowth] = useState(false);
  const [videoError, setVideoError] = useState("");
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const videoContainerRef = useRef<HTMLDivElement | null>(null);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const hasTriggeredReadyRef = useRef(false);
  const commentReadyRef = useRef(false);
  const { status: llmStatus } = useLLMStatus();

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const formattedMediaItems = useMemo(
    () =>
      mediaItems.map((item) => ({
        ...item,
        createdLabel: new Date(item.created_at).toLocaleString(),
        sizeLabel: formatBytes(item.size_bytes),
      })),
    [mediaItems],
  );

  const primaryMedia = formattedMediaItems[0] || null;
  const mediaPlaybackUrl = primaryMedia ? getMediaPlaybackUrl(primaryMedia) : "";
  const isVideoMedia = primaryMedia ? primaryMedia.mime_type.startsWith("video/") : false;

  const segmentBulletCache = useMemo(
    () =>
      Object.fromEntries(
        segments.map((segment) => [segment.id, segment.rewrites?.bullets?.bullets || []]),
      ) as Record<string, string[]>,
    [segments],
  );

  const pauseEvents = pausesToChips(results?.delivery?.pauses?.events || []);
  const fillerEvents = fillerEventsToChips(results?.word_choice?.fillers?.events || []);
  const starterEntries = results?.word_choice?.templates?.sentence_starters?.items || [];
  const repetitionEntries = [
    ...((results?.word_choice?.repetitions?.top_words || []) as WordChoiceChipSource[]),
    ...((results?.word_choice?.repetitions?.top_phrases || []) as WordChoiceChipSource[]),
  ];
  const weakWordEntries = (results?.word_choice?.weak_words?.items || []) as WordChoiceChipSource[];
  const scenarioNorms = (scenarioProfile?.norms || {}) as Record<string, { min: number; max: number; why: string }>;
  const scenarioLabel = session?.scenario_label_ru || t("common.labels.unknown");
  const scenarioGoal = session?.scenario_goal ? t(`scenario.goal.${session.scenario_goal}`) : t("common.labels.unknown");
  const scenarioToneKey = String((scenarioProfile?.tone as string) || "friendly");
  const scenarioToneRu = t(`scenario.tone.${scenarioToneKey}`);
  const goalBlock = results?.coaching?.goal;

  const loadSession = async () => {
    if (!sessionId) {
      setError(t("session.missingId"));
      setLoading(false);
      return;
    }
    try {
      const [data, media, currentStatus, transcriptData, segmentData, commentData, scenarioData] = await Promise.all([
        fetchSession(sessionId),
        fetchSessionMedia(sessionId),
        fetchSessionStatus(sessionId),
        fetchSessionTranscript(sessionId),
        fetchSessionSegments(sessionId),
        fetchSessionComment(sessionId),
        fetchSessionScenario(sessionId),
      ]);
      setSession(data);
      setMediaItems(media);
      setHasMedia(media.length > 0);
      setStatusInfo(currentStatus);
      setTranscript(transcriptData);
      setTranscriptText(transcriptData.text || "");
      setSegments(segmentData);
      setComment(commentData.text || "");
      setSavedComment(commentData.text || "");
      setScenarioProfile((scenarioData.profile as Record<string, any>) || null);
      setCommentStatus("idle");
      commentReadyRef.current = true;
      try {
        const latestResults = await fetchSessionResults(sessionId);
        setResults(latestResults);
      } catch {
        setResults(null);
      }
      setVideoError("");
      setError("");
    } catch {
      setError(t("session.loadError"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSession();
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !statusInfo || !["queued", "processing"].includes(statusInfo.status)) {
      return;
    }

    const interval = window.setInterval(async () => {
      try {
        const latest = await fetchSessionStatus(sessionId);
        setStatusInfo(latest);

        try {
          const latestResults = await fetchSessionResults(sessionId);
          setResults(latestResults);
        } catch {
        }

        if (["ready", "error"].includes(latest.status)) {
          if (latest.status === "ready") {
            const [latestTranscript, latestSegments, latestResults] = await Promise.all([
              fetchSessionTranscript(sessionId),
              fetchSessionSegments(sessionId),
              fetchSessionResults(sessionId),
            ]);
            setTranscript(latestTranscript);
            setTranscriptText(latestTranscript.text || "");
            setSegments(latestSegments);
            setResults(latestResults);
          }
          window.clearInterval(interval);
        }
      } catch {
        window.clearInterval(interval);
      }
    }, 1500);

    return () => window.clearInterval(interval);
  }, [sessionId, statusInfo]);

  useEffect(() => {
    if (!sessionId || !statusInfo) return;
    if (statusInfo.status !== "ready") {
      hasTriggeredReadyRef.current = false;
      return;
    }
    if (hasTriggeredReadyRef.current) return;
    hasTriggeredReadyRef.current = true;

    const timer = window.setTimeout(async () => {
      try {
        const [latestTranscript, latestSegments, latestResults] = await Promise.all([
          fetchSessionTranscript(sessionId),
          fetchSessionSegments(sessionId),
          fetchSessionResults(sessionId),
        ]);
        setTranscript(latestTranscript);
        setTranscriptText(latestTranscript.text || "");
        setSegments(latestSegments);
        setResults(latestResults);
      } catch {
      }
    }, 1000);

    return () => window.clearTimeout(timer);
  }, [sessionId, statusInfo]);

  useEffect(() => {
    if (!sessionId || !commentReadyRef.current) return;
    if (comment === savedComment) return;

    setCommentStatus("saving");
    const timer = window.setTimeout(async () => {
      try {
        const updated = await putSessionComment(sessionId, { text: comment.trim() ? comment : "" });
        const nextValue = updated.text || "";
        setSavedComment(nextValue);
        setComment(nextValue);
        setCommentStatus("saved");
        window.setTimeout(() => {
          setCommentStatus((current) => (current === "saved" ? "idle" : current));
        }, 1400);
      } catch {
        setCommentStatus("error");
      }
    }, 800);

    return () => window.clearTimeout(timer);
  }, [comment, savedComment, sessionId]);

  const resetUploadState = () => {
    setSelectedFile(null);
    setUploadProgress(0);
    if (uploadInputRef.current) {
      uploadInputRef.current.value = "";
    }
  };

  const handleUpload = async () => {
    if (!sessionId || !selectedFile) {
      setUploadError(t("session.chooseFileBeforeUpload"));
      return;
    }

    setUploading(true);
    setUploadError("");
    setVideoError("");
    setUploadProgress(0);
    try {
      await uploadSessionMedia(sessionId, selectedFile, setUploadProgress);
      resetUploadState();
      const [media, latestStatus] = await Promise.all([fetchSessionMedia(sessionId), fetchSessionStatus(sessionId)]);
      setMediaItems(media);
      setHasMedia(media.length > 0);
      setStatusInfo(latestStatus);
    } catch (uploadErr) {
      setUploadError(getUploadErrorMessage(uploadErr));
    } finally {
      setUploading(false);
    }
  };

  const handleClearSelectedFile = () => {
    resetUploadState();
    setUploadError("");
  };

  const handleStartAnalysis = async () => {
    if (!sessionId) {
      return;
    }
    setStartingAnalysis(true);
    setAnalysisError("");
    try {
      await startSessionAnalysis(sessionId);
      setStatusInfo(await fetchSessionStatus(sessionId));
    } catch (analysisErr) {
      setAnalysisError(getAnalysisErrorMessage(analysisErr));
    } finally {
      setStartingAnalysis(false);
    }
  };

  const handleRetry = async () => {
    if (!sessionId) {
      return;
    }
    setStartingAnalysis(true);
    setAnalysisError("");
    try {
      setStatusInfo(await reanalyzeSession(sessionId));
    } catch (analysisErr) {
      setAnalysisError(getAnalysisErrorMessage(analysisErr));
    } finally {
      setStartingAnalysis(false);
    }
  };

  const handleSaveTranscript = async () => {
    if (!sessionId || !transcriptText.trim()) {
      setTranscriptError(t("session.transcriptEmptyError"));
      return;
    }
    setSavingTranscript(true);
    setTranscriptError("");
    try {
      const updated = await patchSessionTranscript(sessionId, { text: transcriptText });
      setTranscript((prev) => ({
        ...(prev || updated),
        ...updated,
        text: transcriptText,
      }));
      setTranscriptText(transcriptText);
      setStatusInfo(await fetchSessionStatus(sessionId));
    } catch (err) {
      setTranscriptError(getAnalysisErrorMessage(err));
    } finally {
      setSavingTranscript(false);
    }
  };

  const handleDeleteSession = async () => {
    if (!sessionId) {
      return;
    }
    setDeleting(true);
    setError("");
    try {
      await deleteSession(sessionId);
      navigate("/progress");
    } catch {
      setError(t("session.deleteError"));
    } finally {
      setDeleting(false);
      setShowDelete(false);
    }
  };

  const tempo = results?.delivery?.tempo;
  const pauses = results?.delivery?.pauses;
  const fillers = results?.word_choice?.fillers;
  const pitch = results?.voice?.pitch;
  const loudness = results?.voice?.loudness;

  const wpmValue = tempo?.wpm_avg?.value ?? null;
  const pauseRatio = pauses?.pause_ratio?.value ?? null;
  const pausePercent = pauseRatio != null ? Number((pauseRatio * 100).toFixed(1)) : null;
  const fillerCount = fillers?.count?.value ?? null;
  const fillerDensity = fillers?.density?.value ?? null;
  const pitchCv = pitch?.cv?.value ?? null;
  const rmsCv = loudness?.rms_cv?.value ?? null;
  const pitchLabel = pitch?.label ?? null;
  const loudnessLabel = loudness?.label ?? null;
  const pitchLabelFormatted = formatVoiceText(pitchLabel);
  const loudnessLabelFormatted = formatVoiceText(loudnessLabel);
  const voiceInsufficientData = t("session.insufficientData");
  const centering = results?.visual?.centering;
  const stability = results?.visual?.stability;
  const eyeContact = results?.visual?.eye_contact;
  const wordChoice = results?.word_choice;
  const starters = wordChoice?.templates?.sentence_starters;
  const repetitions = wordChoice?.repetitions;
  const weakWords = wordChoice?.weak_words;
  const redundancy = wordChoice?.conciseness?.redundancy_score;
  const redundancyPercent = redundancy?.value != null ? Math.round(redundancy.value <= 1 ? redundancy.value * 100 : redundancy.value) : null;
  const weakWordsCount = weakWords?.count?.value ?? null;
  const redundancyRating = redundancyPercent == null
    ? t("session.wordChoiceMetricFallback")
    : redundancyPercent <= 25
      ? t("session.concisenessVerdictGood")
      : redundancyPercent <= 45
        ? t("session.concisenessVerdictOk")
        : t("session.concisenessVerdictBad");
  const windowWpmItems = tempo?.wpm_windows?.length ? tempo.wpm_windows : tempo?.wpm_series || [];
  const wpmNormMin = scenarioNorms.wpm?.min;
  const wpmNormMax = scenarioNorms.wpm?.max;
  const toneRange = useMemo(() => {
    if (typeof wpmNormMin !== "number" || typeof wpmNormMax !== "number") return null;
    if (scenarioToneKey === "calm") return { min: Math.max(90, wpmNormMin - 10), max: Math.max(90, wpmNormMax - 10), explain: t("session.toneExplain.calm") };
    if (scenarioToneKey === "energetic") return { min: Math.min(220, wpmNormMin + 10), max: Math.min(220, wpmNormMax + 10), explain: t("session.toneExplain.energetic") };
    if (scenarioToneKey === "formal") return { min: Math.max(90, wpmNormMin - 5), max: Math.max(90, wpmNormMax - 5), explain: t("session.toneExplain.formal") };
    return { min: wpmNormMin, max: wpmNormMax, explain: t("session.toneExplain.friendly") };
  }, [scenarioToneKey, wpmNormMin, wpmNormMax]);
  const toneVerdictShort = useMemo(() => {
    if (!toneRange || typeof wpmValue !== "number") return "—";
    if (wpmValue < toneRange.min) return "Для тона лучше чуть быстрее.";
    if (wpmValue > toneRange.max) return "Для тона лучше чуть медленнее.";
    return "Темп подходит тону.";
  }, [toneRange, wpmValue]);
  const tempoVerdict = tempo?.wpm_category === "below" ? "Ниже нормы" : tempo?.wpm_category === "above" ? "Выше нормы" : "В норме";
  const speechTiles: CompactTile[] = [
    {
      title: "Слов/мин",
      main: typeof wpmValue === "number" ? String(Math.round(wpmValue)) : "—",
      lines: [
        `Норма: ${formatRange(scenarioNorms.wpm?.min, scenarioNorms.wpm?.max)}`,
        `Тон: ${scenarioToneRu}`,
        toneVerdictShort,
      ],
      tooltipLines: toneRange ? [toneRange.explain, `Рекомендованный темп для тона: ${toneRange.min}–${toneRange.max} слов/мин`] : undefined,
    },
    {
      title: "Темп",
      main: tempoVerdict,
      lines: [
        `Факт: ${typeof wpmValue === "number" ? Math.round(wpmValue) : "—"} слов/мин`,
        `Норма: ${formatRange(scenarioNorms.wpm?.min, scenarioNorms.wpm?.max)}`,
      ],
    },
    {
      title: "Доля пауз",
      main: formatPercent(pausePercent),
      lines: [
        `Норма: ${formatRange(scenarioNorms.pause_percent?.min, scenarioNorms.pause_percent?.max, "%")}`,
        "Паузы помогают структуре.",
      ],
    },
    {
      title: t("session.fillersTitle"),
      main: formatPerMin(fillerDensity),
      lines: [
        `Всего: ${fillerCount ?? "—"}`,
        `Норма: ${formatRange(scenarioNorms.fillers_per_min?.min, scenarioNorms.fillers_per_min?.max)}/мин`,
      ],
    },
    {
      title: "Выбор слов",
      main: `Избыточность: ${redundancyPercent != null ? `${redundancyPercent}%` : "—"}`,
      lines: [
        `Норма: ${formatRange(scenarioNorms.redundancy_percent?.min, scenarioNorms.redundancy_percent?.max, "%")}`,
        `Слабые слова: ${weakWordsCount ?? "—"}`,
      ],
      tooltipLines: [t("session.concisenessTooltip")],
    },
  ];
  const goalSummaryText = (goalBlock?.summary || t("session.coachingPending")).trim();
  const compactCriteria = (goalBlock?.criteria || []).slice(0, 6).map((criterion) => ({
    title: criterion.title,
    score: typeof criterion.score === "number" ? Math.round(criterion.score) : 0,
    explanation: criterion.explanation || criterion.verdict || "",
  }));
  const compactReasons = (goalBlock?.reasons || []).map((reason) => {
    const value = typeof reason.value === "number" ? reason.value : null;
    return {
      metric: String(reason.metric || ""),
      label: metricValueWithNorm(String(reason.metric || ""), value, reason.norm ? String(reason.norm) : undefined),
      impact: metricImpactText(String(reason.metric || ""), value, reason.norm ? String(reason.norm) : undefined),
      dev: (() => {
        const [minRaw, maxRaw] = String(reason.norm || "").split(/[–-]/);
        const min = Number(minRaw);
        const max = Number(maxRaw);
        if (typeof value !== "number" || !Number.isFinite(min) || !Number.isFinite(max)) return 0;
        if (value < min) return min - value;
        if (value > max) return value - max;
        return 0;
      })(),
    };
  }).sort((a, b) => b.dev - a.dev).slice(0, 4).filter((item, idx) => item.dev > 0 || idx < 2);
  const compactActions = (goalBlock?.actions || []).filter(Boolean).slice(0, 5);

  const onTimecodeClick = (timeInSeconds: number) => {
    if (!mediaRef.current) return;
    mediaRef.current.currentTime = timeInSeconds;
    videoContainerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const handleUploadFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    setSelectedFile(event.target.files?.[0] || null);
    setUploadError("");
  };

  const handleRewriteSegment = async (segmentId: string, kind: "short" | "bullets") => {
    if (!sessionId) return;
    const existingSegment = segments.find((segment) => segment.id === segmentId);
    if (kind === "bullets" && existingSegment?.rewrites?.bullets?.bullets?.length) {
      return;
    }
    setSegmentRewriteLoading((prev) => ({ ...prev, [segmentId]: kind }));
    try {
      const rewrite = await rewriteSessionSegment(sessionId, segmentId, kind);
      setSegments((prev) =>
        prev.map((segment) => {
          if (segment.id !== segmentId) return segment;
          return {
            ...segment,
            rewrites: {
              ...segment.rewrites,
              short: kind === "short" ? rewrite as SessionSegment["rewrites"]["short"] : segment.rewrites.short,
              bullets: kind === "bullets" ? rewrite as SessionSegment["rewrites"]["bullets"] : segment.rewrites.bullets,
            },
          };
        }),
      );
    } catch (_error) {
      setTranscriptError(t("session.transcriptRewriteError"));
    } finally {
      setSegmentRewriteLoading((prev) => ({ ...prev, [segmentId]: null }));
    }
  };

  const handleCopyTranscript = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(transcriptText);
      } else {
        const hidden = document.createElement("textarea");
        hidden.value = transcriptText;
        hidden.setAttribute("readonly", "true");
        hidden.style.position = "fixed";
        hidden.style.left = "-9999px";
        document.body.appendChild(hidden);
        hidden.select();
        const copied = document.execCommand("copy");
        document.body.removeChild(hidden);
        if (!copied) throw new Error("copy failed");
      }
      setCopyStatus("success");
    } catch {
      setCopyStatus("error");
    } finally {
      window.setTimeout(() => setCopyStatus("idle"), 1800);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div>
          <h1>{session?.title || t("session.detailsTitle")}</h1>
          <p className="ui-muted">{t("session.subtitle")}</p>
          <p className="session-scenario-badge">{t("session.scenarioBadge", { label: scenarioLabel, goal: scenarioGoal })}</p>
        </div>
        <div className="ui-row">
          <Link to="/progress">
            <Button variant="secondary">{t("common.actions.goToList")}</Button>
          </Link>
          <Button variant="danger" onClick={() => setShowDelete(true)}>
            {t("common.dialog.deletePracticeTitle")}
          </Button>
        </div>
      </CardHeader>

      <CardContent>
        {loading ? (
          <div className="ui-grid">
            <Skeleton />
            <Skeleton />
            <Skeleton />
          </div>
        ) : error ? (
          <ErrorState message={error} onRetry={loadSession} />
        ) : session ? (
          <div className="session-workspace">
            <section className="session-main-column">
              <Card className="session-video-card">
                <CardContent>
                  {primaryMedia ? (
                    isVideoMedia ? (
                      <div ref={videoContainerRef} className="session-video-frame">
                        <video
                          ref={(node) => {
                            mediaRef.current = node;
                          }}
                          className="session-video"
                          controls
                          controlsList="nodownload"
                          preload="metadata"
                          src={mediaPlaybackUrl}
                          onError={() => {
                            const mediaErr = mediaRef.current?.error;
                            const code = mediaErr?.code;
                            const codeText =
                              code === 1
                                ? "MEDIA_ERR_ABORTED"
                                : code === 2
                                  ? "MEDIA_ERR_NETWORK"
                                  : code === 3
                                    ? "MEDIA_ERR_DECODE"
                                    : code === 4
                                      ? "MEDIA_ERR_SRC_NOT_SUPPORTED"
                                      : "UNKNOWN";
                            // eslint-disable-next-line no-console
                            console.error("Video playback error", {
                              code,
                              codeText,
                              currentSrc: mediaRef.current?.currentSrc,
                              networkState: mediaRef.current?.networkState,
                              readyState: mediaRef.current?.readyState,
                            });
                            setVideoError(t("session.uploadVideoError", { code: codeText }));
                          }}
                        />
                      </div>
                    ) : (
                      <div ref={videoContainerRef} className="session-video-frame">
                        <audio
                          ref={(node) => {
                            mediaRef.current = node;
                          }}
                          className="session-video"
                          controls
                          preload="metadata"
                          src={mediaPlaybackUrl}
                        />
                      </div>
                    )
                  ) : (
                    <div className="session-video-empty">
                      <h3>{t("session.noMediaTitle")}</h3>
                      <p className="ui-muted">{t("session.noMediaDescription")}</p>
                    </div>
                  )}

                  {videoError ? <Alert tone="danger">{videoError}</Alert> : null}

                  {!hasMedia ? (
                    <div className="session-upload-panel">
                      <input
                        ref={uploadInputRef}
                        type="file"
                        accept=".mp4,.mov,.webm,.mp3,.wav"
                        onChange={handleUploadFileChange}
                        disabled={uploading}
                      />
                      {selectedFile ? (
                        <div className="session-upload-meta">
                          <div className="ui-muted">
                            {selectedFile.name} • {formatBytes(selectedFile.size)}
                          </div>
                          <Button variant="danger" type="button" onClick={handleClearSelectedFile} disabled={uploading}>
                            {t("practice.removeFile")}
                          </Button>
                        </div>
                      ) : null}
                      {uploading ? <ProgressBar value={uploadProgress} /> : null}
                      <Button onClick={handleUpload} disabled={!selectedFile} loading={uploading}>
                        {t("common.actions.upload")}
                      </Button>
                    </div>
                  ) : (
                    <div className="session-media-meta ui-muted">
                      {primaryMedia?.filename} • {primaryMedia?.sizeLabel}
                    </div>
                  )}

                  {uploadError ? <Alert tone="danger">{uploadError}</Alert> : null}
                </CardContent>
              </Card>

              <Card className="session-transcript-card">
                <CardHeader>
                  <h3>{t("session.transcriptTitle")}</h3>
                </CardHeader>
                <CardContent>
                  <div className="transcript-list">
                    {segments.length ? (
                      segments.map((segment) => {
                        const loadingKind = segmentRewriteLoading[segment.id];
                        const bulletItems = segmentBulletCache[segment.id] || [];
                        return (
                          <div key={segment.id} className="transcript-item">
                            <div className="ui-row transcript-segment-header">
                              <span className="transcript-time">
                                {formatTime(segment.start_sec)}–{formatTime(segment.end_sec)}
                              </span>
                              <Button variant="secondary" type="button" onClick={() => onTimecodeClick(segment.start_sec)}>
                                {t("common.actions.jump")}
                              </Button>
                            </div>
                            <p>{segment.text}</p>
                            <div className="ui-row transcript-actions">
                              <Button type="button" variant="secondary" loading={loadingKind === "short"} onClick={() => handleRewriteSegment(segment.id, "short")}>
                                {t("common.actions.summarizeShort")}
                              </Button>
                              <Button type="button" variant="secondary" loading={loadingKind === "bullets"} onClick={() => handleRewriteSegment(segment.id, "bullets")}>
                                {t("common.actions.summarizeBullets")}
                              </Button>
                            </div>
                            {segment.rewrites?.short?.text ? <blockquote className="transcript-rewrite-short">{t("common.actions.summarizeShort")}: {segment.rewrites.short.text}</blockquote> : null}
                            {bulletItems.length ? (
                              <ul className="transcript-rewrite-bullets">
                                {bulletItems.map((bullet, idx) => (
                                  <li key={`${segment.id}-bullet-${idx}`}>{bullet}</li>
                                ))}
                              </ul>
                            ) : null}
                          </div>
                        );
                      })
                    ) : (
                      <p className="ui-muted">{t("session.transcriptEmpty")}</p>
                    )}
                  </div>
                  <div className="session-transcript-edit">
                    <p className="session-edit-subheading">{t("session.transcriptEditTitle")}</p>
                    <Textarea
                      placeholder={t("session.transcriptPlaceholder")}
                      value={transcriptText}
                      onChange={(event) => setTranscriptText(event.target.value)}
                    />
                    <div className="ui-row">
                      <Button onClick={handleSaveTranscript} loading={savingTranscript}>{t("common.actions.saveAndRecalculate")}</Button>
                      <Button variant="secondary" onClick={handleCopyTranscript}>{t("session.copyTranscript")}</Button>
                      {copyStatus === "success" ? <span className="ui-muted">{t("session.copySuccess")}</span> : null}
                      {copyStatus === "error" ? <span className="ui-muted">{t("session.copyFailed")}</span> : null}
                      <span className="ui-muted">{t("common.labels.language")}: {transcript?.language || t("common.labels.unknown")}</span>
                    </div>
                  </div>
                  {transcriptError ? <Alert tone="danger">{transcriptError}</Alert> : null}
                </CardContent>
              </Card>

              <Card className="session-comment-card">
                <CardHeader>
                  <h3>{t("session.commentTitle")}</h3>
                </CardHeader>
                <CardContent>
                  <Textarea
                    placeholder={t("session.commentPlaceholder")}
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                  />
                  <div className="session-comment-meta">
                    <span className="session-comment-status">{commentStatus === "saving" ? t("session.commentSaving") : commentStatus === "saved" ? t("session.commentSaved") : commentStatus === "error" ? t("session.commentSaveError") : t("session.commentHint")}</span>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setComment("");
                      }}
                      disabled={!comment.trim()}
                    >
                      {t("common.actions.delete")}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </section>

            <aside className="session-side-column">
              <Card>
                <CardContent>
                  <AnalysisProgress
                    statusInfo={statusInfo}
                    hasMedia={hasMedia}
                    startingAnalysis={startingAnalysis}
                    analysisError={analysisError}
                    onStart={handleStartAnalysis}
                    onRetry={handleRetry}
                    llmStatus={llmStatus}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <h3>{t("session.voiceTitle")}</h3>
                </CardHeader>
                <CardContent>
                  <div className="metric-grid">
                    <div className="metric-card">
                      <span className="ui-muted session-title-with-help">
                        Интонация
                        <span className="session-help-icon" title={t("session.pitchTooltip")} aria-label={t("session.pitchTooltip")}>i</span>
                      </span>
                      <div className="session-inline-value-sm session-voice-label">{pitchLabelFormatted}</div>
                      <span className="ui-muted session-voice-line">Значение: {pitchCv != null ? pitchCv.toFixed(3) : "-"}</span>
                      {scenarioNorms.pitch_cv ? <span className="ui-muted session-voice-line">{`Норма: ${scenarioNorms.pitch_cv.min}–${scenarioNorms.pitch_cv.max}`}</span> : null}
                      {pitchCv == null ? <span className="ui-muted">{voiceInsufficientData}</span> : null}
                    </div>
                    <div className="metric-card">
                      <span className="ui-muted session-title-with-help">
                        Громкость
                        <span className="session-help-icon" title={t("session.loudnessTooltip")} aria-label={t("session.loudnessTooltip")}>i</span>
                      </span>
                      <div className="session-inline-value-sm session-voice-label">{loudnessLabelFormatted}</div>
                      <span className="ui-muted session-voice-line">Значение: {rmsCv != null ? rmsCv.toFixed(3) : "-"}</span>
                      {rmsCv == null ? <span className="ui-muted">{voiceInsufficientData}</span> : null}
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <h3>{t("session.visualsTitle")}</h3>
                </CardHeader>
                <CardContent>
                  <div className="metric-grid">
                    <div className="metric-card">
                      <span className="ui-muted">{t("progress.charts.centering")}</span>
                      <div className="session-inline-value-lg">{centering?.value != null ? `${Math.round(centering.value)}/100` : "-"}</div>
                      <span className="ui-muted">{centering?.note || t("session.visualNoData")}</span>
                    </div>
                    <div className="metric-card">
                      <span className="ui-muted">{t("progress.charts.posture")}</span>
                      <div className="session-inline-value-lg">{stability?.value != null ? `${Math.round(stability.value)}/100` : "-"}</div>
                      <span className="ui-muted">{stability?.note || t("session.visualNoData")}</span>
                    </div>
                    <div className="metric-card">
                      <span className="ui-muted">{t("progress.charts.eyeContact")}</span>
                      <div className="session-inline-value-lg">{eyeContact?.value != null ? `${Math.round(eyeContact.value)}/5` : "-"}</div>
                      {scenarioNorms.eye_contact ? (
                        <div className="ui-muted">
                          {t("scenario.normPrefixShort", { value: `${scenarioNorms.eye_contact.min}–${scenarioNorms.eye_contact.max}` })}
                        </div>
                      ) : null}
                      <div className="ui-muted">{eyeContact?.note || t("session.visualNoData")}</div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <h3>{t("session.speechTitle")}</h3>
                </CardHeader>
                <CardContent>
                  {!scenarioProfile ? (
                    <Alert tone="warning">
                      {t("session.scenarioMissingWarning")} <Link to="/practice">{t("session.openScenarioEditor")}</Link>
                    </Alert>
                  ) : null}
                  <div className="metric-grid speech-tiles-grid">
                    {speechTiles.map((tile, idx) => (
                      <div className="metric-card metric-card-compact" key={`speech-tile-${idx}`}>
                        <div className="session-tile-header">
                          <span className="ui-muted">{tile.title}</span>
                          {tile.tooltipLines?.length ? <span className="session-help-icon" title={tile.tooltipLines.join("\n")} aria-label={tile.tooltipLines.join(". ")}>ⓘ</span> : null}
                        </div>
                        <div className="session-inline-value-lg session-tile-main">{tile.main}</div>
                        {tile.lines.slice(0, 3).map((line, lineIdx) => (
                          <span className="ui-muted session-clamp-1" key={`tile-line-${idx}-${lineIdx}`}>{line}</span>
                        ))}
                      </div>
                    ))}
                  </div>

                  <Tabs
                    value={insightTab}
                    onChange={setInsightTab}
                    items={[
                      { key: "coaching", label: t("session.coachingTab") },
                      { key: "analytics", label: t("session.detailsTab") },
                    ]}
                  />
                  <p className="ui-muted session-timecodes-hint">{t("session.clickableTimecodesHint")}</p>

                  {insightTab === "coaching" ? (
                    <div className="ui-grid session-insight-grid">
                      <Card className="insight-card">
                        <CardContent>
                          <h4>{t("scenario.goalCardTitle")}</h4>
                          <span className="session-goal-chip">
                            {goalBlock?.achieved === "yes" ? t("scenario.goalAchievedYes") : goalBlock?.achieved === "no" ? t("scenario.goalAchievedNo") : t("scenario.goalAchievedPartial")}
                          </span>
                          <p className="session-clamp-2">{goalSummaryText}</p>
                          {compactCriteria.length > 0 ? (
                            <>
                              <p className="ui-muted">Оценка по целевым критериям</p>
                              <ul className="session-goal-criteria-list">
                                {compactCriteria.map((criterion, idx) => (
                                  <li key={`goal-criterion-${idx}`} className="session-goal-criterion">
                                    <div className="session-goal-criterion-head">
                                      <strong>{criterion.title}</strong>
                                      <span className={`session-score-badge ${criterion.score >= 85 ? "is-high" : criterion.score >= 60 ? "is-mid" : "is-low"}`}>
                                        <span className="session-score-dot" />
                                        {criterion.score}
                                      </span>
                                    </div>
                                    <p className="ui-muted session-goal-criterion-text">{criterion.explanation}</p>
                                    <div className="session-score-track" aria-hidden="true">
                                      <span style={{ width: `${Math.max(4, Math.min(100, criterion.score))}%` }} />
                                    </div>
                                  </li>
                                ))}
                              </ul>
                            </>
                          ) : null}
                          {compactReasons.length > 0 ? (
                            <>
                              <p className="ui-muted">Почему так</p>
                              <ul className="metric-list session-goal-reasons-list">
                                {compactReasons.map((reason, idx) => (
                                  <li key={`goal-reason-${idx}`}>
                                    <strong className="session-clamp-1">{reason.label}</strong>
                                    <p className="session-clamp-2">{reason.impact}</p>
                                  </li>
                                ))}
                              </ul>
                            </>
                          ) : null}
                          <p className="ui-muted">Что улучшить дальше</p>
                          <ul className="metric-list session-action-chip-list">
                            {compactActions.map((action, idx) => <li key={`goal-action-${idx}`}><span className="session-clamp-2">{action}</span></li>)}
                          </ul>
                        </CardContent>
                      </Card>
                      <Card className="insight-card">
                        <CardContent>
                          <h4>{results?.coaching?.strength?.title || t("session.coachingStrengthTitle")}</h4>
                          {results?.status !== "ready" ? <p className="session-primary-text">{t("session.coachingPending")}</p> : (
                            <div className="session-insight-list">
                              {((results?.coaching?.strength_v2?.items || []).length ? (results?.coaching?.strength_v2?.items || []) : [{ title: t("session.coachingStrengthTitle"), text: results?.coaching?.strength?.text || t("session.strengthDefault"), evidence: [], metrics: [] }]).slice(0, showAllStrength ? 99 : 3).map((item, idx) => (
                                <div className="session-insight-item" key={`strength-v2-${idx}`}>
                                  <strong>{item.title}</strong>
                                  <p className="session-clamp-1">{item.text}</p>
                                  {(item.evidence || []).length ? <ul>{item.evidence.map((ev, eidx) => <li key={`strength-ev-${idx}-${eidx}`}>{String(ev).replace(/\bWPM\b/gi, "слов/мин").replace(/pitch_cv/gi, "вариативность интонации")}</li>)}</ul> : null}
                                </div>
                              ))}
                              {((results?.coaching?.strength_v2?.items || []).length > 3) ? <Button variant="secondary" type="button" onClick={() => setShowAllStrength((prev) => !prev)}>{showAllStrength ? "Скрыть" : "Показать ещё"}</Button> : null}
                            </div>
                          )}
                        </CardContent>
                      </Card>
                      <Card className="insight-card">
                        <CardContent>
                          <h4>{results?.coaching?.growth?.title || t("session.coachingGrowthTitle")}</h4>
                          {results?.status !== "ready" ? <p className="session-primary-text">{t("session.coachingPending")}</p> : (
                            <div className="session-insight-list">
                              {((results?.coaching?.growth_v2?.items || []).length ? (results?.coaching?.growth_v2?.items || []) : [{ title: t("session.coachingGrowthTitle"), text: t("session.growthDefault"), why_for_scenario: "", action: "", evidence: [], metrics: [] }]).slice(0, showAllGrowth ? 99 : 3).map((item, idx) => (
                                <div className="session-insight-item" key={`growth-v2-${idx}`}>
                                  <strong>{item.title}</strong>
                                  <p className="session-clamp-1">{item.text}</p>
                                  {item.why_for_scenario ? <p className="session-growth-why session-clamp-1">{item.why_for_scenario}</p> : null}
                                  {item.action ? <p className="session-growth-action session-clamp-1">{item.action}</p> : null}
                                  {(item.evidence || []).length ? <ul>{item.evidence.map((ev, eidx) => <li key={`growth-ev-${idx}-${eidx}`}>{String(ev).replace(/\bWPM\b/gi, "слов/мин").replace(/pitch_cv/gi, "вариативность интонации")}</li>)}</ul> : null}
                                </div>
                              ))}
                              {((results?.coaching?.growth_v2?.items || []).length > 3) ? <Button variant="secondary" type="button" onClick={() => setShowAllGrowth((prev) => !prev)}>{showAllGrowth ? "Скрыть" : "Показать ещё"}</Button> : null}
                            </div>
                          )}
                        </CardContent>
                      </Card>
                      <Card className="insight-card">
                        <CardContent>
                          <h4>{results?.coaching?.questions?.title || t("session.coachingQuestionsTitle")}</h4>
                          <p className="ui-muted">{t("session.questionsHelp")}</p>
                          <ul className="metric-list session-question-list">
                            {(results?.status === "ready"
                              ? (results?.coaching?.questions?.items?.length
                                  ? results.coaching.questions.items
                                  : ["—"])
                              : [t("session.coachingPending")]
                            ).map((item, idx) => (
                              <li key={`coaching-questions-${idx}`}><span>{item}</span></li>
                            ))}
                          </ul>
                        </CardContent>
                      </Card>
                      <Card className="insight-card">
                        <CardContent>
                          <h4>{`${results?.coaching?.summary?.title || t("session.coachingSummaryTitle")} · ${t("session.summaryTitleSuffix")}`}</h4>
                          {results?.coaching?.summary?.source === "fallback" ? <p className="ui-muted">Показано базовое резюме (AI недоступен)</p> : null}
                          <ul className="metric-list">
                            {(results?.status === "ready" ? (results?.coaching?.summary?.bullets || []) : [t("session.coachingPending")]).map((item, idx) => (
                              <li key={`coaching-summary-${idx}`}><span>{item}</span></li>
                            ))}
                          </ul>
                          <h4>{t("session.keywordsTitle")}</h4>
                          <div className="session-keywords-row">
                            {(
                              results?.coaching?.keywords?.items?.length
                              ? results.coaching.keywords.items
                              : results?.coaching?.summary?.keywords?.length
                                ? results.coaching.summary.keywords
                              : []
                            ).map((keyword, idx) => (
                              <span key={`keyword-${idx}`} className="session-keyword-pill">{keyword}</span>
                            ))}
                            {!results?.coaching?.keywords?.items?.length && !results?.coaching?.summary?.keywords?.length ? <span className="ui-muted">—</span> : null}
                          </div>
                        </CardContent>
                      </Card>
                    </div>
                  ) : (
                    <div className="ui-grid session-insight-grid">
                      <div>
                        <h4>{t("session.windowWpmTitle")}</h4>
                        <ul className="metric-list">
                          {windowWpmItems.map((item, index) => {
                            const timelineSpans = Array.isArray(item.timeline_spans) ? item.timeline_spans : [];
                            const seekStart = typeof item.seek_to_sec === "number"
                              ? item.seek_to_sec
                              : timelineSpans.length && typeof timelineSpans[0]?.[0] === "number"
                                ? timelineSpans[0][0]
                              : typeof item.t_start === "number"
                                ? item.t_start
                                : null;
                            const speechFrom = typeof item.speech_from_sec === "number" ? item.speech_from_sec : item.speech_t_start;
                            const speechTo = typeof item.speech_to_sec === "number" ? item.speech_to_sec : item.speech_t_end;
                            const speechActiveSec = typeof item.speech_sec === "number" ? item.speech_sec : item.speech_active_sec;
                            return (
                              <li key={item.idx || `${item.label || "wpm"}-${index}`}>
                                <div className="session-wpm-window-copy">
                                  <span>{speechFrom != null && speechTo != null ? `Речь ${formatTime(speechFrom)}–${formatTime(speechTo)}` : item.label || "-"}</span>
                                </div>
                                <div className="ui-row session-inline-gap">
                                  <strong>{speechActiveSec != null && speechActiveSec < 2 ? "-" : item.wpm ?? item.value ?? "-"}</strong>
                                  {seekStart != null ? (
                                    <Button variant="secondary" type="button" onClick={() => onTimecodeClick(seekStart)}>
                                      {formatTime(seekStart)}
                                    </Button>
                                  ) : null}
                                </div>
                              </li>
                            );
                          })}
                          {!windowWpmItems.length ? <li><span className="ui-muted">{t("common.labels.noData")}</span></li> : null}
                        </ul>
                      </div>
                      <div>
                        <h4>{t("session.pausesTitle")}</h4>
                        <p className="ui-muted session-inline-no-margin">{t("session.pausesInfo")}</p>
                        <ul className="metric-list">
                          {pauseEvents.slice(0, 8).map((pause, index) => (
                            <li key={`${pause.t}-${index}`}>
                              <span>{pause.label || formatTime(pause.t)}</span>
                              <Button variant="secondary" type="button" onClick={() => onTimecodeClick(pause.t)}>
                                {getTimecodeLabel(pause, t("session.pauseButtonSuffix"))}
                              </Button>
                            </li>
                          ))}
                          {!pauseEvents.length ? <li><span className="ui-muted">{t("common.labels.noData")}</span></li> : null}
                        </ul>
                      </div>
                      <div>
                        <h4>{t("session.fillersTitle")}</h4>
                        <ul className="metric-list">
                          {fillerEvents.slice(0, 10).map((filler, index) => (
                            <li key={`${filler.t}-${index}`}>
                              <span>{filler.label || t("session.fillersTitle")}</span>
                              <Button variant="secondary" type="button" onClick={() => onTimecodeClick(filler.t)}>
                                {getTimecodeLabel(filler)}
                              </Button>
                            </li>
                          ))}
                          {!fillerEvents.length ? <li><span className="ui-muted">{t("common.labels.noData")}</span></li> : null}
                        </ul>
                      </div>
                      <Card className="insight-card">
                        <CardContent>
                          <h4 className="session-title-with-help">
                            <span>{t("session.concisenessTitle")}</span>
                            <span className="session-help-icon" title={t("session.concisenessTooltip")} aria-label={t("session.concisenessTooltip")}>i</span>
                          </h4>
                          <div className="session-inline-value-md">{redundancyPercent != null ? `${redundancyPercent}%` : "-"}</div>
                          <p className="ui-muted">{redundancyPercent != null ? redundancyRating : (redundancy?.note || t("common.labels.noData"))}</p>
                        </CardContent>
                      </Card>
                      <Card className="insight-card">
                        <CardContent>
                          <h4>{t("session.templatesTitle")}</h4>
                          <p className="ui-muted">{starters?.note || t("common.labels.noData")}</p>
                          {renderWordChoiceBlocks(starterEntries, onTimecodeClick, (item) => `«${item.starter}» - ${Math.round((item.ratio || 0) * 100)}% (${item.count || 0})`)}
                        </CardContent>
                      </Card>
                      <Card className="insight-card">
                        <CardContent>
                          <h4>{t("session.repeatsTitle")}</h4>
                          <p className="ui-muted">{repetitions?.note || t("common.labels.noData")}</p>
                          {renderWordChoiceBlocks(repetitionEntries, onTimecodeClick, (item) => {
                            const label = item.word || item.phrase || "-";
                            return `${label} - ${item.count || 0}`;
                          }, t("session.repeatLabel"))}
                        </CardContent>
                      </Card>
                      <Card className="insight-card">
                        <CardContent>
                          <h4>{t("session.weakWordsTitle")}</h4>
                          {renderWordChoiceBlocks(weakWordEntries, onTimecodeClick, (item) => `${item.word || "-"}`)}
                        </CardContent>
                      </Card>
                    </div>
                  )}
                </CardContent>
              </Card>
            </aside>
          </div>
        ) : null}
      </CardContent>

      <Dialog
        open={showDelete}
        title={t("common.dialog.deletePracticeTitle")}
        description={t("common.dialog.deletePracticeDescription")}
        confirmText={t("common.actions.delete")}
        loading={deleting}
        onConfirm={handleDeleteSession}
        onCancel={() => setShowDelete(false)}
      />
    </Card>
  );
};

const renderWordChoiceBlocks = (
  items: WordChoiceChipSource[],
  seekTo: (timeInSeconds: number) => void,
  getLabel: (item: WordChoiceChipSource) => string,
  fallbackTimecodeLabel?: string,
) => {
  if (!items.length) {
    return <p className="ui-muted">{t("common.labels.noData")}</p>;
  }

  return items.slice(0, 3).map((item, itemIndex) => (
    <div key={`${getLabel(item)}-${itemIndex}`} className="session-inline-block-gap">
      <div className="session-inline-text-strong">{getLabel(item)}</div>
      <div className="ui-row session-inline-wrap">
        {(item.timecodes || []).slice(0, 10).map((timecode, idx) => (
          <Button key={`${getLabel(item)}-${idx}`} variant="secondary" type="button" onClick={() => seekTo(timecode.t)}>
            {getTimecodeLabel(timecode, fallbackTimecodeLabel)}
          </Button>
        ))}
      </div>
    </div>
  ));
};

const pausesToChips = (events: Array<{ start?: number; end?: number; dur?: number; t?: number; label?: string; kind?: string }>): TimecodeChip[] => {
  const chips: TimecodeChip[] = [];

  for (const event of events) {
    const eventTime = getEventTime(event);
    if (eventTime == null) continue;

    const range = typeof event.start === "number" && typeof event.end === "number"
      ? `${formatTime(event.start)}–${formatTime(event.end)}`
      : formatTime(eventTime);
    const duration = typeof event.dur === "number" ? formatTime(event.dur) : "";

    chips.push({
      t: eventTime,
      label: [range, duration].filter(Boolean).join(" · "),
      kind: event.kind,
    });
  }

  return chips;
};

const fillerEventsToChips = (events: Array<{ phrase: string; start: number; end: number; t?: number; label?: string; kind?: string }>): TimecodeChip[] => {
  const chips: TimecodeChip[] = [];

  for (const event of events) {
    const eventTime = getEventTime(event);
    if (eventTime == null) continue;

    chips.push({
      t: eventTime,
      label: event.label || `${event.phrase} · ${formatTime(event.start)}–${formatTime(event.end)}`,
      kind: event.kind,
    });
  }

  return chips;
};


const getUploadErrorMessage = (error: unknown) => {
  if (error && (error as AxiosError).isAxiosError) {
    const axiosError = error as AxiosError<{ detail?: string }>;
    if (axiosError.response?.status === 401) return t("errors.sessionExpired");
    if (axiosError.response?.status === 404) return t("session.uploadNotFound");
    if (axiosError.response?.status === 409) {
      return axiosError.response?.data?.detail || t("session.uploadConflict");
    }
    if (axiosError.response?.status === 413) return t("session.uploadTooLarge");
    if (axiosError.response?.status === 415) return t("session.uploadUnsupported");
    return axiosError.response?.data?.detail || t("session.uploadGeneric");
  }
  return t("session.uploadGeneric");
};

const getAnalysisErrorMessage = (error: unknown) => {
  if (error && (error as AxiosError).isAxiosError) {
    const axiosError = error as AxiosError<{ detail?: string }>;
    return axiosError.response?.data?.detail || t("session.analysisStartError");
  }
  return t("session.analysisStartError");
};

export default SessionDetailsPage;
