import { HTMLAttributes } from "react";

import "./Skeleton.css";
import { cn } from "./utils";

const Skeleton = ({ className, ...props }: HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("ui-skeleton", className)} {...props} />
);

export default Skeleton;
