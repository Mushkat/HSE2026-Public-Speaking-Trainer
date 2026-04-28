import { HTMLAttributes } from "react";

import "./Alert.css";
import { cn } from "./utils";

type AlertTone = "info" | "success" | "warning" | "danger";

type AlertProps = HTMLAttributes<HTMLDivElement> & {
  tone?: AlertTone;
};

const Alert = ({ className, tone = "info", ...props }: AlertProps) => (
  <div className={cn("ui-alert", `ui-alert--${tone}`, className)} role="alert" {...props} />
);

export default Alert;
