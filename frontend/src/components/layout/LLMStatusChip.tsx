import { t } from "../../i18n";
import "./LLMStatusChip.css";
import { useLLMStatus } from "./LLMStatusContext";

const CHIP_META = {
  ready: {
    label: t("llm.readyLabel"),
    className: "llm-chip llm-chip--ready",
    tooltip: t("llm.readyTooltip"),
  },
  starting: {
    label: t("llm.startingLabel"),
    className: "llm-chip llm-chip--starting",
    tooltip: t("llm.startingTooltip"),
  },
  unavailable: {
    label: t("llm.unavailableLabel"),
    className: "llm-chip llm-chip--unavailable",
    tooltip: t("llm.unavailableTooltip"),
  },
} as const;

const LLMStatusChip = () => {
  const { status } = useLLMStatus();
  const meta = CHIP_META[status.status] || CHIP_META.unavailable;

  return (
    <span className={meta.className} title={meta.tooltip} aria-label={meta.tooltip}>
      <span className="llm-chip__dot" aria-hidden="true" />
      <span>{meta.label}</span>
    </span>
  );
};

export default LLMStatusChip;
