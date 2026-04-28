import { createContext, PropsWithChildren, useContext, useEffect, useMemo, useState } from "react";

import { getToken } from "../../api/auth";
import { t } from "../../i18n";
import { fetchLLMStatus, LLMStatus } from "../../api/system";

const FALLBACK_STATUS: LLMStatus = {
  available: false,
  status: "unavailable",
  detail: t("llm.fallbackNote"),
};

type LLMStatusContextValue = {
  status: LLMStatus;
};

const LLMStatusContext = createContext<LLMStatusContextValue>({ status: FALLBACK_STATUS });

export const LLMStatusProvider = ({ children }: PropsWithChildren) => {
  const [status, setStatus] = useState<LLMStatus>({
    available: false,
    status: "starting",
    detail: t("llm.checking"),
  });

  useEffect(() => {
    let cancelled = false;
    let intervalId: number | null = null;

    const loadStatus = async () => {
      if (!getToken()) {
        if (!cancelled) setStatus(FALLBACK_STATUS);
        return;
      }
      try {
        const next = await fetchLLMStatus();
        if (!cancelled) setStatus(next);
      } catch {
        if (!cancelled) {
          setStatus({
            available: false,
            status: "unavailable",
            detail: t("llm.fallbackNote"),
          });
        }
      }
    };

    void loadStatus();
    if (getToken()) {
      intervalId = window.setInterval(() => {
        void loadStatus();
      }, 15000);
    }

    return () => {
      cancelled = true;
      if (intervalId != null) window.clearInterval(intervalId);
    };
  }, []);

  const value = useMemo(() => ({ status }), [status]);

  return <LLMStatusContext.Provider value={value}>{children}</LLMStatusContext.Provider>;
};

export const useLLMStatus = () => useContext(LLMStatusContext);
