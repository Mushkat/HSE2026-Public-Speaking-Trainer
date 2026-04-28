import { ReactNode } from "react";

import { t } from "../../i18n";
import "./Dialog.css";
import Button from "./Button";

type DialogProps = {
  open: boolean;
  title: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
};

const Dialog = ({
  open,
  title,
  description,
  confirmText = t("common.dialog.confirm"),
  cancelText = t("common.dialog.cancel"),
  loading = false,
  onConfirm,
  onCancel,
  children,
}: DialogProps) => {
  if (!open) {
    return null;
  }

  return (
    <div className="ui-dialog-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="ui-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <h3>{title}</h3>
        {description ? <p className="ui-muted">{description}</p> : null}
        {children}
        <div className="ui-dialog__actions">
          <Button variant="ghost" onClick={onCancel}>
            {cancelText}
          </Button>
          <Button variant="danger" onClick={onConfirm} loading={loading}>
            {confirmText}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default Dialog;
