import { createContext, ReactNode, useContext, useMemo, useState } from "react";

import "./Toast.css";

type ToastTone = "success" | "warning" | "danger" | "info";

type ToastItem = {
  id: number;
  message: string;
  tone: ToastTone;
};

type ToastContextValue = {
  pushToast: (message: string, tone?: ToastTone) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export const ToastProvider = ({ children }: { children: ReactNode }) => {
  const [items, setItems] = useState<ToastItem[]>([]);

  const contextValue = useMemo<ToastContextValue>(
    () => ({
      pushToast: (message, tone = "info") => {
        const id = Date.now() + Math.floor(Math.random() * 1000);
        setItems((prev) => [...prev, { id, message, tone }]);
        window.setTimeout(() => {
          setItems((prev) => prev.filter((item) => item.id !== id));
        }, 3200);
      },
    }),
    [],
  );

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <div className="ui-toast-stack" aria-live="polite" aria-atomic="true">
        {items.map((item) => (
          <div key={item.id} className={`ui-toast ui-toast--${item.tone}`}>
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return ctx;
};
