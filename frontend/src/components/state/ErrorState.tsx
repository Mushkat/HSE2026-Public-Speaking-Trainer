import { t } from "../../i18n";
import "./EmptyState.css";
import "./ErrorState.css";
import Alert from "../ui/Alert";
import Button from "../ui/Button";

type ErrorStateProps = {
  message: string;
  onRetry?: () => void;
};

const ErrorState = ({ message, onRetry }: ErrorStateProps) => (
  <div className="ui-state">
    <Alert tone="danger">{message}</Alert>
    {onRetry ? (
      <Button variant="secondary" onClick={onRetry}>
        {t("common.actions.retry")}
      </Button>
    ) : null}
  </div>
);

export default ErrorState;
