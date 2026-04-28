import { ReactNode } from "react";

import "./EmptyState.css";
import Button from "../ui/Button";

type EmptyStateProps = {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: ReactNode;
};

const EmptyState = ({ title, description, actionLabel, onAction, icon }: EmptyStateProps) => (
  <div className="ui-state">
    <div className="ui-state__icon">{icon || "○"}</div>
    <h3>{title}</h3>
    <p className="ui-muted">{description}</p>
    {actionLabel && onAction ? (
      <Button variant="secondary" onClick={onAction}>
        {actionLabel}
      </Button>
    ) : null}
  </div>
);

export default EmptyState;
