import { useEffect, useMemo, useState } from "react";

import { SessionStatus } from "../../api/sessions";
import { LLMStatus } from "../../api/system";
import { t } from "../../i18n";
import "./AnalysisProgress.css";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import ProgressBar from "../ui/ProgressBar";

const STEP_RANGES: Array<{ key: string; label: string; start: number; end: number; aliases?: string[] }> = [
  { key: "preprocess", label: t("analysis.steps.preprocess"), start: 0, end: 25, aliases: ["queued", "waiting_for_start"] },
  { key: "asr", label: t("analysis.steps.asr"), start: 25, end: 50 },
  { key: "metrics", label: t("analysis.steps.metrics"), start: 50, end: 75, aliases: ["visual"] },
  { key: "coaching", label: t("analysis.steps.coaching"), start: 75, end: 100, aliases: ["finalize", "ready"] },
];

const statusLabel = (status?: SessionStatus["status"] | null) => {
  if (status === "queued") return t("common.status.queued");
  if (status === "processing") return t("common.status.processing");
  if (status === "ready") return t("common.status.ready");
  if (status === "error") return t("common.status.error");
  return t("analysis.waiting");
};

const resolveStepIndex = (step?: string | null, status?: SessionStatus["status"] | null) => {
  if (status === "ready") return STEP_RANGES.length;
  if (!step) return 0;
  const index = STEP_RANGES.findIndex((item) => item.key === step || item.aliases?.includes(step));
  return index >= 0 ? index : 0;
};

const normalizeProgress = (value?: number | null) => {
  if (typeof value !== "number" || Number.isNaN(value)) return 0;
  const fixed = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(fixed)));
};

const AnalysisProgress = ({
  statusInfo,
  hasMedia,
  startingAnalysis,
  analysisError,
  onStart,
  onRetry,
  llmStatus,
}: {
  statusInfo: SessionStatus | null;
  hasMedia: boolean;
  startingAnalysis: boolean;
  analysisError: string;
  onStart: () => void;
  onRetry: () => void;
  llmStatus: LLMStatus;
}) => {
  const targetProgress = normalizeProgress(statusInfo?.progress);
  const [smoothProgress, setSmoothProgress] = useState(targetProgress);

  useEffect(() => {
    let frame = 0;
    const start = smoothProgress;
    const end = Math.max(start, targetProgress);
    if (start === end) return undefined;
    const startedAt = performance.now();
    const duration = 420;

    const animate = (now: number) => {
      const elapsed = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - elapsed, 3);
      setSmoothProgress(Math.round(start + (end - start) * eased));
      if (elapsed < 1) frame = window.requestAnimationFrame(animate);
    };

    frame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frame);
  }, [smoothProgress, targetProgress]);

  const currentStepIndex = useMemo(() => resolveStepIndex(statusInfo?.step, statusInfo?.status), [statusInfo?.step, statusInfo?.status]);
  const currentStep = STEP_RANGES[Math.min(currentStepIndex, STEP_RANGES.length - 1)];
  const stepProgress = currentStep
    ? Math.max(8, Math.min(100, Math.round(((smoothProgress - currentStep.start) / Math.max(currentStep.end - currentStep.start, 1)) * 100)))
    : smoothProgress;
  const isRunning = statusInfo ? ["queued", "processing"].includes(statusInfo.status) : false;
  const isReady = statusInfo?.status === "ready";
  const isError = statusInfo?.status === "error";

  return (
    <div className="analysis-progress-card">
      <div className="analysis-progress-card__header">
        <div>
          <span className="ui-muted">{t("common.labels.analysisStatus")}</span>
          <h3>{isReady ? t("analysis.completed") : isError ? t("analysis.failed") : t("analysis.inProgress")}</h3>
          <p className="analysis-progress-card__subtitle">{t("analysis.subtitle")}</p>
        </div>
        <div className="analysis-progress-card__meta">
          <span className={`ui-badge ui-badge--${statusInfo?.status || "queued"}`}>{statusLabel(statusInfo?.status)}</span>
          <strong>{smoothProgress}%</strong>
        </div>
      </div>

      {llmStatus.status !== "ready" ? <Alert tone="info">{t("llm.fallbackNote")}</Alert> : null}

      {isRunning ? (
        <div className="analysis-stepper" aria-live="polite">
          {STEP_RANGES.map((step, index) => {
            const state = isReady || index < currentStepIndex ? "done" : index === currentStepIndex ? "active" : "pending";
            return (
              <div key={step.key} className={`analysis-step analysis-step--${state}`}>
                <div className="analysis-step__icon" aria-hidden="true">
                  {state === "done" ? "✓" : state === "active" ? "●" : "○"}
                </div>
                <div className="analysis-step__body">
                  <div className="analysis-step__title-row">
                    <span className="analysis-step__title">{step.label}</span>
                    {state === "active" ? <span className="analysis-step__percent">{Math.max(0, Math.min(100, stepProgress))}%</span> : null}
                  </div>
                  {state === "active" ? <ProgressBar value={stepProgress} className="analysis-step__progress" /> : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}

      {hasMedia && !isRunning && !isReady ? (
        <Button onClick={onStart} loading={startingAnalysis}>
          {t("common.actions.startAnalysis")}
        </Button>
      ) : null}

      {isError ? (
        <div className="analysis-error-card">
          <Alert tone="danger">{statusInfo?.error_message || t("analysis.failedDefault")}</Alert>
          <div className="ui-row">
            <Button variant="secondary" onClick={onRetry} loading={startingAnalysis}>
              {t("common.actions.reanalyze")}
            </Button>
            <Button
              variant="ghost"
              onClick={() => void navigator.clipboard?.writeText(statusInfo?.error_message || analysisError || t("analysis.failedDefault"))}
            >
              {t("common.actions.reportIssue")}
            </Button>
          </div>
        </div>
      ) : null}

      {analysisError ? <Alert tone="danger">{analysisError}</Alert> : null}
    </div>
  );
};

export default AnalysisProgress;
