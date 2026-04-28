import { HTMLAttributes } from "react";

import "./ProgressBar.css";
import { cn } from "./utils";

type ProgressBarProps = HTMLAttributes<HTMLProgressElement> & {
  value: number;
};

const ProgressBar = ({ value, className, ...props }: ProgressBarProps) => (
  <progress className={cn("ui-progress", className)} max={100} value={Math.min(100, Math.max(0, value))} {...props} />
);

export default ProgressBar;
