import { HTMLAttributes } from "react";

import { SessionStatus } from "../../api/sessions";
import { t } from "../../i18n";
import "./Badge.css";
import { cn } from "./utils";

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  status: SessionStatus["status"];
};

const Badge = ({ status, className, ...props }: BadgeProps) => (
  <span className={cn("ui-badge", `ui-badge--${status}`, className)} {...props}>
    {t(`common.status.${status}`)}
  </span>
);

export default Badge;
