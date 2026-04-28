import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { createSession, deleteSession, fetchSessionsSummary, SessionSummaryItem } from "../api/sessions";
import { t } from "../i18n";
import "./ProgressPage.css";
import EmptyState from "../components/state/EmptyState";
import ErrorState from "../components/state/ErrorState";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import { Card, CardContent, CardHeader } from "../components/ui/Card";
import Dialog from "../components/ui/Dialog";
import Input from "../components/ui/Input";
import Skeleton from "../components/ui/Skeleton";
import { useToast } from "../components/ui/Toast";

type SessionWithMetrics = SessionSummaryItem & {
  wpmAvg?: number;
  pausePercent?: number;
  fillerPerMin?: number;
  redundancyPercent?: number;
  pitchCv?: number;
  rmsCv?: number;
  centering?: number;
  stability?: number;
  eyeContact?: number;
  eyeContactPct?: number;
};

type ChartPoint = {
  label: string;
  fullLabel: string;
  sessionTitle: string;
  values: Record<string, number | null>;
};

type AxisConfig = {
  key: "left" | "right";
  min: number;
  max: number;
  label: string;
  tickFormatter?: (value: number) => string;
};

type SeriesConfig = {
  key: string;
  label: string;
  color: string;
  axis: "left" | "right";
  formatter: (value: number | null) => string;
};

type DeltaMeta = { text: string; tone: "good" | "bad" | "neutral" };

type ReferenceLineConfig = {
  axis: "left" | "right";
  value: number;
  color: string;
  label?: string;
};

type ReferenceBandConfig = {
  axis: "left" | "right";
  min: number;
  max: number;
  color: string;
};

const CHART_WIDTH = 760;
const CHART_HEIGHT = 250;
const CHART_PADDING = { top: 16, right: 56, bottom: 34, left: 56 };

const ProgressPage = () => {
  const navigate = useNavigate();
  const { pushToast } = useToast();

  const [sessions, setSessions] = useState<SessionWithMetrics[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [dialogSessionId, setDialogSessionId] = useState<string | null>(null);
  const [visibleRange, setVisibleRange] = useState<"10" | "20" | "all">("10");
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);

  const loadSessions = async () => {
    setLoading(true);
    try {
      const summary = await fetchSessionsSummary();
      const withMetrics = summary.map((session) => {
        const pauseRatio = typeof session.summary.pause_ratio === "number" ? session.summary.pause_ratio : undefined;
        const fillerPerMin = typeof session.summary.filler_per_min === "number" ? session.summary.filler_per_min : undefined;
        const redundancyScore = typeof session.summary.redundancy_score === "number" ? session.summary.redundancy_score : undefined;
        const eyeContact = typeof session.summary.eye_contact === "number" ? session.summary.eye_contact : undefined;
        return {
          ...session,
          wpmAvg: typeof session.summary.wpm_avg === "number" ? session.summary.wpm_avg : undefined,
          pausePercent: typeof pauseRatio === "number" ? roundValue(pauseRatio * 100, 1) : undefined,
          fillerPerMin,
          redundancyPercent: typeof redundancyScore === "number" ? normalizeRedundancyPercent(redundancyScore) : undefined,
          pitchCv: typeof session.summary.pitch_cv === "number" ? session.summary.pitch_cv : undefined,
          rmsCv: typeof session.summary.rms_cv === "number" ? session.summary.rms_cv : undefined,
          centering: typeof session.summary.centering === "number" ? session.summary.centering : undefined,
          stability: typeof session.summary.stability === "number" ? session.summary.stability : undefined,
          eyeContact,
          eyeContactPct: typeof eyeContact === "number" ? roundValue((eyeContact / 5) * 100, 1) : undefined,
        };
      });
      setSessions(withMetrics);
      setError("");
    } catch {
      setError(t("progress.loadError"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSessions();
  }, []);

  const handleCreate = async () => {
    setCreating(true);
    setError("");
    try {
      const session = await createSession(title.trim() || undefined);
      pushToast(t("progress.createSuccess"), "success");
      navigate(`/sessions/${session.id}`);
    } catch {
      setError(t("progress.createError"));
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (sessionId: string) => {
    setDeletingId(sessionId);
    setError("");
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((session) => session.id !== sessionId));
      pushToast(t("progress.deleteSuccess"), "warning");
    } catch {
      setError(t("progress.deleteError"));
    } finally {
      setDeletingId(null);
      setDialogSessionId(null);
    }
  };

  const weeklyCount = useMemo(() => {
    const threshold = Date.now() - 7 * 24 * 60 * 60 * 1000;
    return sessions.filter((session) => new Date(session.created_at).getTime() >= threshold).length;
  }, [sessions]);

  const readyCount = useMemo(() => sessions.filter((session) => session.status === "ready").length, [sessions]);
  const processingCount = useMemo(() => sessions.filter((session) => session.status === "processing").length, [sessions]);

  const chartSessionsAsc = useMemo(
    () => [...sessions].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()),
    [sessions],
  );

  const listSessionsDesc = useMemo(
    () => [...sessions].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [sessions],
  );

  const visibleChartSessions = useMemo(() => {
    if (visibleRange === "all") return chartSessionsAsc;
    return chartSessionsAsc.slice(-Number(visibleRange));
  }, [chartSessionsAsc, visibleRange]);

  const chartPoints = useMemo<ChartPoint[]>(() => {
    return visibleChartSessions.map((session, index) => ({
      label: `${index + 1}`,
      fullLabel: formatChartDate(session.created_at),
      sessionTitle: session.title || `${t("nav.practice")} ${index + 1}`,
      values: {
        wpm: session.wpmAvg ?? null,
        pausePercent: session.pausePercent ?? null,
        fillers: session.fillerPerMin ?? null,
        redundancyPercent: session.redundancyPercent ?? null,
        centering: session.centering ?? null,
        eyeContactPct: session.eyeContactPct ?? null,
        stability: session.stability ?? null,
      },
    }));
  }, [visibleChartSessions]);

  return (
    <div className="progress-layout">
      <Card className="progress-list-card">
        <CardHeader>
          <div>
            <h1>{t("progress.title")}</h1>
            <p className="ui-muted">{t("progress.subtitle")}</p>
          </div>
        </CardHeader>
        <CardContent>
          <div className="ui-row">
            <div className="progress-create-input">
              <Input placeholder={t("progress.newSessionPlaceholder")} value={title} onChange={(event) => setTitle(event.target.value)} />
            </div>
            <Button type="button" onClick={handleCreate} loading={creating}>
              {t("progress.newSessionButton")}
            </Button>
          </div>

          {error ? <ErrorState message={error} onRetry={loadSessions} /> : null}

          {loading ? (
            <div className="ui-grid">
              <Skeleton />
              <Skeleton />
              <Skeleton />
            </div>
          ) : sessions.length === 0 ? (
            <EmptyState
              title={t("common.empty.noPracticesTitle")}
              description={t("showcase.noSessionsDescription")}
              actionLabel={t("progress.newSessionButton")}
              onAction={handleCreate}
            />
          ) : (
            <ul className="session-list sessions-list-narrow">
              {listSessionsDesc.map((session, index) => (
                <li key={session.id} className="session-item progress-session-item">
                  <div className="progress-session-main">
                    <div className="progress-session-header">
                      <div>
                        <div className="progress-session-title">{session.title || t("home.untitled")}</div>
                        <div className="ui-muted">{new Date(session.created_at).toLocaleString()}</div>
                        <div className="ui-muted">{`${t("scenario.titleShort")}: ${session.scenario_label_ru || t("common.labels.unknown")} · ${t("scenario.goalLabel")}: ${session.scenario_goal ? t(`scenario.goal.${session.scenario_goal}`) : t("common.labels.unknown")}`}</div>
                      </div>
                      <div className="ui-row progress-session-tags">
                        <Badge status={session.status} />
                        <span className="progress-attempt-chip">{t("progress.attempt", { value: listSessionsDesc.length - index })}</span>
                      </div>
                    </div>

                    <div className="progress-badge-group">
                      <MetricChip label={t("common.labels.wpm")} value={typeof session.wpmAvg === "number" ? `${Math.round(session.wpmAvg)}` : "-"} tone={wpmTone(session.wpmAvg)} />
                      <MetricChip label={t("progress.charts.pauses")} value={typeof session.pausePercent === "number" ? `${session.pausePercent}%` : "-"} tone={pauseTone(session.pausePercent)} />
                      <MetricChip label={t("progress.charts.fillers")} value={typeof session.fillerPerMin === "number" ? `${session.fillerPerMin}${t("common.labels.perMinute")}` : "-"} tone={fillersTone(session.fillerPerMin)} />
                    </div>

                    <div className="progress-session-details">
                      <Button
                        variant="ghost"
                        type="button"
                        className="progress-details-button"
                        onClick={() => setExpandedSessionId((current) => (current === session.id ? null : session.id))}
                      >
                        {t("common.actions.details")}
                      </Button>
                      {expandedSessionId === session.id ? (
                        <div className="progress-badge-group">
                          <MetricChip label={t("progress.charts.redundancy")} value={typeof session.redundancyPercent === "number" ? `${session.redundancyPercent}%` : "-"} tone={redundancyTone(session.redundancyPercent)} />
                          <MetricChip label={t("progress.charts.centering")} value={typeof session.centering === "number" ? `${Math.round(session.centering)}/100` : "-"} tone={thresholdTone(session.centering, 80)} />
                          <MetricChip label={t("progress.charts.eyeContact")} value={typeof session.eyeContact === "number" ? `${session.eyeContact}/5` : "-"} tone={thresholdTone(session.eyeContact ? session.eyeContact * 20 : undefined, 80)} />
                          <MetricChip label={t("progress.charts.posture")} value={typeof session.stability === "number" ? `${Math.round(session.stability)}/100` : "-"} tone={thresholdTone(session.stability, 80)} />
                          <MetricChip label="Вариативность интонации" value={typeof session.pitchCv === "number" ? session.pitchCv.toFixed(2) : "-"} tone="neutral" />
                          <MetricChip label="Стабильность громкости" value={typeof session.rmsCv === "number" ? session.rmsCv.toFixed(2) : "-"} tone="neutral" />
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="ui-row progress-session-actions">
                    <Button variant="secondary" type="button" onClick={() => navigate(`/sessions/${session.id}`)}>
                      {t("common.actions.open")}
                    </Button>
                    <Button variant="danger" type="button" onClick={() => setDialogSessionId(session.id)}>
                      {t("common.actions.delete")}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="progress-charts-card">
        <CardHeader className="progress-charts-header">
          <div>
            <h2>{t("progress.chartsTitle")}</h2>
            <p className="ui-muted">{t("progress.chartsSubtitle")}</p>
            <p className="ui-muted">{t("progress.scenarioHint")}</p>
          </div>
          <div className="progress-range-toggle" role="group" aria-label={t("progress.rangeLabel")}>
            {[
              { value: "10", label: "10" },
              { value: "20", label: "20" },
              { value: "all", label: t("progress.charts.rangeAll") },
            ].map((option) => (
              <button
                key={option.value}
                type="button"
                className={`progress-range-toggle__button ${visibleRange === option.value ? "is-active" : ""}`}
                onClick={() => setVisibleRange(option.value as "10" | "20" | "all")}
              >
                {option.label}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="progress-charts-stack">
          <div className="metric-grid">
            <KpiCard label={t("progress.kpi.total")} value={sessions.length} />
            <KpiCard label={t("progress.kpi.week")} value={weeklyCount} />
            <KpiCard label={t("progress.kpi.ready")} value={readyCount} />
            <KpiCard label={t("progress.kpi.processing")} value={processingCount} />
          </div>

          <ProgressChartCard
            title={t("progress.charts.tempoTitle")}
            subtitle={t("progress.charts.tempoSubtitle")}
            points={chartPoints}
            leftAxis={{ key: "left", min: 80, max: 220, label: t("common.labels.wpm"), tickFormatter: (value) => `${Math.round(value)}` }}
            rightAxis={{ key: "right", min: 0, max: 40, label: t("progress.charts.pausesAxis"), tickFormatter: (value) => `${Math.round(value)}%` }}
            series={[
              { key: "wpm", label: t("progress.charts.speechRate"), color: "#1814f3", axis: "left", formatter: (value) => (typeof value === "number" ? `${Math.round(value)} слов/мин` : "-") },
              { key: "pausePercent", label: t("progress.charts.pauses"), color: "#16dbcc", axis: "right", formatter: (value) => (typeof value === "number" ? `${value}%` : "-") },
            ]}
            referenceBands={[
              { axis: "left", min: 140, max: 160, color: "rgba(24, 20, 243, 0.08)" },
              { axis: "right", min: 10, max: 25, color: "rgba(22, 219, 204, 0.10)" },
            ]}
            referenceLines={[]}
            axisNotes={{ left: [t("progress.charts.paceNorm")], right: [t("progress.charts.pauseNorm")] }}
            renderTooltip={(point) => (
              <>
                <strong>{point.sessionTitle}</strong>
                <span>{point.fullLabel}</span>
                <span>{t("progress.charts.tempoTooltipWpm", { value: formatNullable(point.values.wpm, (value) => `${Math.round(value)} слов/мин · ${wpmNormLabel(value)}`) })}</span>
                <span>{t("progress.charts.tempoTooltipPause", { value: formatNullable(point.values.pausePercent, (value) => `${value}% · ${pauseNormLabel(value)}`) })}</span>
              </>
            )}
            lowerIsBetterKeys={["pausePercent"]}
          />

          <ProgressChartCard
            title={t("progress.charts.speechCleanTitle")}
            subtitle={t("progress.charts.speechCleanSubtitle")}
            points={chartPoints}
            leftAxis={{ key: "left", min: 0, max: 3.5, label: t("progress.charts.fillersAxis"), tickFormatter: (value) => value.toFixed(1) }}
            rightAxis={{ key: "right", min: 0, max: 60, label: t("progress.charts.redundancyAxis"), tickFormatter: (value) => `${Math.round(value)}%` }}
            series={[
              { key: "fillers", label: t("progress.charts.fillers"), color: "#ff8f6b", axis: "left", formatter: (value) => (typeof value === "number" ? `${value}${t("common.labels.perMinute")}` : "-") },
              { key: "redundancyPercent", label: t("progress.charts.redundancy"), color: "#7c4dff", axis: "right", formatter: (value) => (typeof value === "number" ? `${value}%` : "-") },
            ]}
            referenceBands={[
              { axis: "left", min: 0, max: 1, color: "rgba(255, 143, 107, 0.10)" },
              { axis: "right", min: 0, max: 25, color: "rgba(124, 77, 255, 0.08)" },
            ]}
            referenceLines={[
              { axis: "left", value: 1, color: "#d7b18a" },
              { axis: "right", value: 25, color: "#c5b4f1" },
            ]}
            axisNotes={{ left: [t("progress.charts.fillersGoal")], right: [t("progress.charts.redundancyGoal")] }}
            renderTooltip={(point) => (
              <>
                <strong>{point.sessionTitle}</strong>
                <span>{point.fullLabel}</span>
                <span>{t("progress.charts.cleanTooltipFillers", { value: formatNullable(point.values.fillers, (value) => `${value}${t("common.labels.perMinute")} · ${fillersNormLabel(value)}`) })}</span>
                <span>{t("progress.charts.cleanTooltipRedundancy", { value: formatNullable(point.values.redundancyPercent, (value) => `${value}% · ${redundancyNormLabel(value)}`) })}</span>
              </>
            )}
            lowerIsBetterKeys={["fillers", "redundancyPercent"]}
          />

          <ProgressChartCard
            title={t("progress.charts.cameraTitle")}
            subtitle={t("progress.charts.cameraSubtitle")}
            points={chartPoints}
            leftAxis={{ key: "left", min: 0, max: 100, label: t("progress.charts.scoreAxis"), tickFormatter: (value) => `${Math.round(value)}` }}
            series={[
              { key: "centering", label: t("progress.charts.centering"), color: "#1d4ed8", axis: "left", formatter: (value) => (typeof value === "number" ? `${Math.round(value)}/100` : "-") },
              { key: "eyeContactPct", label: t("progress.charts.eyeContact"), color: "#14b8a6", axis: "left", formatter: (value) => (typeof value === "number" ? `${Math.round(value)}%` : "-") },
            ]}
            referenceBands={[{ axis: "left", min: 80, max: 100, color: "rgba(20, 184, 166, 0.08)" }]}
            referenceLines={[]}
            axisNotes={{ left: [t("progress.charts.centeringGoal"), t("progress.charts.eyeContactGoal")] }}
            renderTooltip={(point) => (
              <>
                <strong>{point.sessionTitle}</strong>
                <span>{point.fullLabel}</span>
                <span>{t("progress.charts.cameraTooltipCentering", { value: formatNullable(point.values.centering, (value) => `${Math.round(value)}/100 · ${thresholdLabel(value, 80, true)}`) })}</span>
                <span>{t("progress.charts.cameraTooltipEyeContact", { value: formatNullable(point.values.eyeContactPct, (value) => `${Math.round(value)}% · ${thresholdLabel(value, 80, true)}`) })}</span>
                <span>{t("progress.charts.cameraTooltipPosture", { value: formatNullable(point.values.stability, (value) => `${Math.round(value)}/100`) })}</span>
              </>
            )}
            lowerIsBetterKeys={[]}
          />
        </CardContent>
      </Card>

      <Dialog
        open={Boolean(dialogSessionId)}
        title={t("common.dialog.deletePracticeTitle")}
        description={t("common.dialog.deletePracticeDescription")}
        confirmText={t("common.actions.delete")}
        loading={deletingId === dialogSessionId}
        onConfirm={() => (dialogSessionId ? handleDelete(dialogSessionId) : undefined)}
        onCancel={() => setDialogSessionId(null)}
      />
    </div>
  );
};

const KpiCard = ({ label, value }: { label: string; value: number }) => (
  <div className="metric-card">
    <span className="ui-muted">{label}</span>
    <div className="progress-kpi-value">{value}</div>
  </div>
);

const MetricChip = ({ label, value, tone }: { label: string; value: string; tone: "good" | "ok" | "bad" | "neutral" }) => (
  <span className={`progress-chip progress-chip--${tone}`}>
    <strong>{label}:</strong> {value}
  </span>
);

const ProgressChartCard = ({
  title,
  subtitle,
  points,
  leftAxis,
  rightAxis,
  series,
  referenceBands = [],
  referenceLines,
  axisNotes,
  renderTooltip,
  lowerIsBetterKeys = [],
}: {
  title: string;
  subtitle: string;
  points: ChartPoint[];
  leftAxis: AxisConfig;
  rightAxis?: AxisConfig;
  series: SeriesConfig[];
  referenceBands?: ReferenceBandConfig[];
  referenceLines: ReferenceLineConfig[];
  axisNotes?: Partial<Record<AxisConfig["key"], string[]>>;
  renderTooltip: (point: ChartPoint) => ReactNode;
  lowerIsBetterKeys?: string[];
}) => {
  const [hoverIndex, setHoverIndex] = useState<number | null>(points.length ? points.length - 1 : null);
  const innerWidth = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const innerHeight = CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
  const resolvedHoverIndex = hoverIndex != null && points[hoverIndex] ? hoverIndex : points.length ? points.length - 1 : null;
  const hoveredPoint = resolvedHoverIndex != null ? points[resolvedHoverIndex] : null;
  const deltas = useMemo(() => buildSeriesDeltas(points, series, lowerIsBetterKeys), [points, series, lowerIsBetterKeys]);

  const axisMap: Record<AxisConfig["key"], AxisConfig> = {
    left: leftAxis,
    right: rightAxis || leftAxis,
  };

  if (!points.length) {
    return (
      <Card>
        <CardContent>
          <h4>{title}</h4>
          <p className="ui-muted">{subtitle}</p>
          <div className="progress-chart-empty">{t("progress.charts.empty")}</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <div className="progress-chart-card__header">
          <div className="progress-chart-meta">
            <div>
              <h4>{title}</h4>
              <p className="ui-muted">{subtitle}</p>
              <div className="progress-chart-deltas">
                {deltas.length ? deltas.map((delta) => <span key={delta.text} className={`progress-chart-delta progress-chart-delta--${delta.tone}`}>{delta.text}</span>) : <span className="ui-muted">{t("progress.charts.deltaNoData")}</span>}
              </div>
              {lowerIsBetterKeys.length ? <p className="ui-muted progress-lower-hint">{t("progress.charts.lowerIsBetterHint")}</p> : null}
            </div>
          </div>
          <div className="progress-chart-axis-legend">
            <span><strong>{t("progress.charts.axisLeft")}:</strong> {[leftAxis.label, ...(axisNotes?.left || [])].join(" · ")}</span>
            {rightAxis ? <span><strong>{t("progress.charts.axisRight")}:</strong> {[rightAxis.label, ...(axisNotes?.right || [])].join(" · ")}</span> : null}
          </div>
        </div>

        <div className="progress-chart-shell">
          <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} className="progress-chart-svg" role="img" aria-label={title}>
            <rect x={0} y={0} width={CHART_WIDTH} height={CHART_HEIGHT} fill="transparent" />
            {[0, 1].map((ratio) => {
              const y = CHART_PADDING.top + innerHeight * ratio;
              return <line key={ratio} x1={CHART_PADDING.left} y1={y} x2={CHART_WIDTH - CHART_PADDING.right} y2={y} stroke="#edf1ff" strokeWidth={1} />;
            })}

            {referenceBands.map((band, index) => {
              const axis = axisMap[band.axis];
              const top = scaleY(band.max, axis, innerHeight);
              const bottom = scaleY(band.min, axis, innerHeight);
              return <rect key={`${band.axis}-${band.min}-${band.max}-${index}`} x={CHART_PADDING.left} y={top} width={innerWidth} height={Math.max(0, bottom - top)} fill={band.color} />;
            })}

            {referenceLines.map((referenceLine, index) => {
              const axis = axisMap[referenceLine.axis];
              const y = scaleY(referenceLine.value, axis, innerHeight);
              return <line key={`${referenceLine.axis}-${referenceLine.value}-${index}`} x1={CHART_PADDING.left} y1={y} x2={CHART_WIDTH - CHART_PADDING.right} y2={y} stroke={referenceLine.color} strokeDasharray="6 6" strokeWidth={1.5} opacity={0.9} />;
            })}

            {[0, 0.5, 1].map((ratio) => {
              const leftValue = leftAxis.max - ratio * (leftAxis.max - leftAxis.min);
              const y = CHART_PADDING.top + innerHeight * ratio;
              return <text key={`left-${ratio}`} x={CHART_PADDING.left - 10} y={y + 4} textAnchor="end" className="progress-chart-axis-label">{leftAxis.tickFormatter ? leftAxis.tickFormatter(leftValue) : `${Math.round(leftValue)}`}</text>;
            })}
            {rightAxis
              ? [0, 0.5, 1].map((ratio) => {
                  const rightValue = rightAxis.max - ratio * (rightAxis.max - rightAxis.min);
                  const y = CHART_PADDING.top + innerHeight * ratio;
                  return <text key={`right-${ratio}`} x={CHART_WIDTH - CHART_PADDING.right + 10} y={y + 4} textAnchor="start" className="progress-chart-axis-label">{rightAxis.tickFormatter ? rightAxis.tickFormatter(rightValue) : `${Math.round(rightValue)}`}</text>;
                })
              : null}

            <text x={CHART_PADDING.left} y={CHART_PADDING.top - 2} className="progress-chart-axis-title">{capitalizeFirst(leftAxis.label)}</text>
            {rightAxis ? <text x={CHART_WIDTH - CHART_PADDING.right} y={CHART_PADDING.top - 2} textAnchor="end" className="progress-chart-axis-title">{capitalizeFirst(rightAxis.label)}</text> : null}

            {series.map((item) => {
              const axis = axisMap[item.axis];
              const path = buildLinePath(points, item.key, axis, innerWidth, innerHeight);
              return path ? <path key={item.key} d={path} fill="none" stroke={item.color} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" /> : null;
            })}

            {points.map((point, index) => {
              const x = scaleX(index, points.length, innerWidth);
              const isActive = resolvedHoverIndex === index;
              return (
                <g key={`${point.label}-${index}`}>
                  <line x1={x} y1={CHART_PADDING.top} x2={x} y2={CHART_HEIGHT - CHART_PADDING.bottom} stroke={isActive ? "#d6defa" : "transparent"} strokeWidth={1.5} />
                  {series.map((item) => {
                    const value = point.values[item.key];
                    if (typeof value !== "number") return null;
                    const y = scaleY(value, axisMap[item.axis], innerHeight);
                    return (
                      <circle key={`${item.key}-${index}`} cx={x} cy={y} r={isActive ? 5 : 4} fill={item.color} stroke="#ffffff" strokeWidth={2} onMouseEnter={() => setHoverIndex(index)}>
                        <title>{`${item.label}: ${item.formatter(value)}`}</title>
                      </circle>
                    );
                  })}
                  <text x={x} y={CHART_HEIGHT - 10} textAnchor="middle" className="progress-chart-x-label">{point.label}</text>
                </g>
              );
            })}
          </svg>

          <div className="progress-chart-tooltip" aria-live="polite">
            {hoveredPoint ? renderTooltip(hoveredPoint) : <span>{t("progress.charts.hoverHint")}</span>}
          </div>
        </div>
        <div className="progress-chart-legend progress-chart-legend--below">
          {series.map((item) => (
            <span key={item.key} className="progress-chart-legend__item">
              <svg className="progress-chart-legend__dot" viewBox="0 0 10 10" aria-hidden="true"><circle cx="5" cy="5" r="5" fill={item.color} /></svg>
              {item.label}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
};

function buildSeriesDeltas(points: ChartPoint[], series: SeriesConfig[], lowerIsBetterKeys: string[]): DeltaMeta[] {
  if (points.length < 2) return [];
  const prev = points[points.length - 2];
  const curr = points[points.length - 1];
  const deltas: DeltaMeta[] = [];
  series.forEach((item) => {
    const prevValue = prev.values[item.key];
    const currValue = curr.values[item.key];
    if (typeof prevValue !== "number" || typeof currValue !== "number") return;
    const delta = roundValue(currValue - prevValue, 1);
    if (delta === 0) {
      deltas.push({ text: t("progress.charts.deltaPrefix", { value: `${item.label}: ${t("progress.charts.deltaEqual")}` }), tone: "neutral" });
      return;
    }
    const lowerIsBetter = lowerIsBetterKeys.includes(item.key);
    const isBetter = lowerIsBetter ? delta < 0 : delta > 0;
    const sign = delta > 0 ? "+" : "−";
    const unit = item.key.includes("Percent") || item.key === "pausePercent" ? "%" : "";
    const text = t("progress.charts.deltaPrefix", {
      value: `${item.label}: ${sign}${Math.abs(delta)}${unit} (${isBetter ? t("progress.charts.deltaBetter") : t("progress.charts.deltaWorse")})`,
    });
    deltas.push({ text, tone: isBetter ? "good" : "bad" });
  });
  return deltas;
}

function buildLinePath(points: ChartPoint[], key: string, axis: AxisConfig, innerWidth: number, innerHeight: number) {
  let currentSegment = "";
  const segments: string[] = [];

  points.forEach((point, index) => {
    const value = point.values[key];
    if (typeof value !== "number") {
      if (currentSegment) {
        segments.push(currentSegment);
        currentSegment = "";
      }
      return;
    }

    const x = scaleX(index, points.length, innerWidth);
    const y = scaleY(value, axis, innerHeight);
    currentSegment = `${currentSegment ? `${currentSegment} L` : "M"} ${x} ${y}`;
  });

  if (currentSegment) segments.push(currentSegment);
  return segments.join(" ");
}

function scaleX(index: number, total: number, innerWidth: number) {
  const step = total <= 1 ? 0 : innerWidth / (total - 1);
  return CHART_PADDING.left + step * index;
}

function scaleY(value: number, axis: AxisConfig, innerHeight: number) {
  const clamped = Math.max(axis.min, Math.min(axis.max, value));
  const ratio = (clamped - axis.min) / Math.max(axis.max - axis.min, 1);
  return CHART_PADDING.top + innerHeight - ratio * innerHeight;
}

function roundValue(value: number, digits = 2) {
  return Number(value.toFixed(digits));
}

function formatChartDate(value: string) {
  return new Date(value).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

function formatNullable(value: number | null | undefined, formatter: (value: number) => string) {
  return typeof value === "number" ? formatter(value) : "-";
}

function capitalizeFirst(value: string) {
  if (!value) return value;
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function wpmNormLabel(value: number) {
  if (value < 140) return t("progress.charts.belowNorm");
  if (value > 160) return t("progress.charts.aboveNorm");
  return t("progress.charts.inNorm");
}

function pauseNormLabel(value: number) {
  if (value < 10) return t("progress.charts.belowNorm");
  if (value > 25) return t("progress.charts.aboveNorm");
  return t("progress.charts.inNorm");
}

function fillersNormLabel(value: number) {
  if (value <= 1) return t("progress.charts.goalReached");
  if (value <= 2) return t("progress.charts.moderate");
  return t("progress.charts.high");
}

function redundancyNormLabel(value: number) {
  if (value <= 25) return t("progress.charts.goalReached");
  if (value <= 45) return t("progress.charts.moderate");
  return t("progress.charts.high");
}

function thresholdLabel(value: number, threshold: number, reverseGood = false) {
  if (reverseGood) {
    return value >= threshold ? t("progress.charts.inNorm") : t("progress.charts.belowGoal");
  }
  return value <= threshold ? t("progress.charts.inNorm") : t("progress.charts.aboveGoal");
}

function thresholdTone(value: number | undefined, threshold: number) {
  if (typeof value !== "number") return "neutral" as const;
  if (value >= threshold) return "good" as const;
  if (value >= threshold - 15) return "ok" as const;
  return "bad" as const;
}

function wpmTone(value: number | undefined) {
  if (typeof value !== "number") return "neutral" as const;
  if (value >= 140 && value <= 160) return "good" as const;
  if (value >= 120 && value <= 180) return "ok" as const;
  return "bad" as const;
}

function pauseTone(value: number | undefined) {
  if (typeof value !== "number") return "neutral" as const;
  if (value >= 10 && value <= 25) return "good" as const;
  if (value >= 6 && value <= 30) return "ok" as const;
  return "bad" as const;
}

function fillersTone(value: number | undefined) {
  if (typeof value !== "number") return "neutral" as const;
  if (value <= 1) return "good" as const;
  if (value <= 2) return "ok" as const;
  return "bad" as const;
}

function redundancyTone(value: number | undefined) {
  if (typeof value !== "number") return "neutral" as const;
  if (value <= 25) return "good" as const;
  if (value <= 45) return "ok" as const;
  return "bad" as const;
}

function normalizeRedundancyPercent(value: number) {
  const normalized = value <= 1 ? value * 100 : value;
  return roundValue(normalized, 1);
}

export default ProgressPage;
