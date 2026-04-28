import { useState } from "react";

import { t } from "../i18n";
import "./UiShowcasePage.css";
import EmptyState from "../components/state/EmptyState";
import ErrorState from "../components/state/ErrorState";
import Alert from "../components/ui/Alert";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import { Card, CardContent, CardFooter, CardHeader } from "../components/ui/Card";
import Dialog from "../components/ui/Dialog";
import Input from "../components/ui/Input";
import ProgressBar from "../components/ui/ProgressBar";
import Skeleton from "../components/ui/Skeleton";
import { Tabs } from "../components/ui/Tabs";
import Textarea from "../components/ui/Textarea";
import { useToast } from "../components/ui/Toast";

const UiShowcasePage = () => {
  const [tab, setTab] = useState<"components" | "states">("components");
  const [dialogOpen, setDialogOpen] = useState(false);
  const { pushToast } = useToast();

  return (
    <div className="page-stack">
      <Card>
        <CardHeader>
          <div>
            <h1>{t("showcase.title")}</h1>
            <p className="ui-muted">{t("showcase.subtitle")}</p>
          </div>
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { key: "components", label: t("showcase.componentsTab") },
              { key: "states", label: t("showcase.statesTab") },
            ]}
          />
        </CardHeader>
        <CardContent>
          {tab === "components" ? (
            <>
              <div className="ui-row">
                <Button>{t("showcase.primary")}</Button>
                <Button variant="secondary">{t("showcase.secondary")}</Button>
                <Button variant="ghost">{t("showcase.ghost")}</Button>
                <Button variant="danger">{t("showcase.danger")}</Button>
                <Button loading>{t("showcase.loading")}</Button>
              </div>
              <div className="ui-grid">
                <Input label={t("showcase.email")} placeholder="name@company.com" />
                <Textarea label={t("showcase.notes")} placeholder={t("showcase.notesPlaceholder")} />
              </div>
              <div className="ui-row">
                <Badge status="queued" />
                <Badge status="processing" />
                <Badge status="ready" />
                <Badge status="error" />
              </div>
              <ProgressBar value={64} />
              <Skeleton className="ui-showcase-skeleton" />
              <Alert tone="warning">{t("showcase.warning")}</Alert>
              <div className="ui-row">
                <Button onClick={() => setDialogOpen(true)} variant="secondary">
                  {t("common.actions.openDialog")}
                </Button>
                <Button onClick={() => pushToast(t("showcase.saved"), "success")}>{t("showcase.showNotification")}</Button>
              </div>
            </>
          ) : (
            <>
              <EmptyState
                title={t("common.empty.noPracticesTitle")}
                description={t("showcase.noSessionsDescription")}
                actionLabel={t("showcase.createAction")}
                onAction={() => pushToast(t("showcase.actionDone"), "info")}
              />
              <ErrorState message={t("showcase.listError")} onRetry={() => pushToast(t("showcase.retryRequested"), "warning")} />
            </>
          )}
        </CardContent>
        <CardFooter>
          <span className="ui-muted">{t("showcase.footer")}</span>
        </CardFooter>
      </Card>

      <Dialog
        open={dialogOpen}
        title={t("common.dialog.deleteItemTitle")}
        description={t("common.dialog.deleteItemDescription")}
        confirmText={t("common.actions.delete")}
        onConfirm={() => {
          pushToast(t("showcase.deleted"), "danger");
          setDialogOpen(false);
        }}
        onCancel={() => setDialogOpen(false)}
      />
    </div>
  );
};

export default UiShowcasePage;
