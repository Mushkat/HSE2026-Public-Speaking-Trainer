import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { fetchSessions, fetchSessionStatus, Session, SessionStatus } from "../api/sessions";
import { getI18nValue, t } from "../i18n";
import "./HomePage.css";
import EmptyState from "../components/state/EmptyState";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import { Card, CardContent, CardHeader } from "../components/ui/Card";
import Skeleton from "../components/ui/Skeleton";

type SessionWithStatus = Session & {
  status: SessionStatus["status"] | "unknown";
};

const HomePage = () => {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionWithStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const howItWorks = getI18nValue<string[]>("home.howItWorksList");
  const recordingTips = getI18nValue<string[]>("home.recordingTips");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const list = await fetchSessions();
        const latest = list.slice(0, 5);
        const withStatus = await Promise.all(
          latest.map(async (session) => {
            try {
              const statusData = await fetchSessionStatus(session.id);
              return { ...session, status: statusData.status };
            } catch {
              return { ...session, status: "unknown" as const };
            }
          }),
        );
        setSessions(withStatus);
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  return (
    <div className="page-stack">
      <Card className="home-hero">
        <CardHeader>
          <div>
            <h2>{t("home.title")}</h2>
            <h3 className="home-cta-title">{t("home.ctaTitle")}</h3>
            <p className="ui-muted home-cta-text">{t("home.ctaText")}</p>
          </div>
          <div className="ui-row home-hero-actions">
            <Link to="/practice">
              <Button className="home-main-cta">{t("home.mainButton")}</Button>
            </Link>
          </div>
        </CardHeader>
      </Card>

      <div className="home-info-columns">
        <Card className="home-info-card">
          <CardHeader>
            <div className="home-info-card-header">
              <h3>{t("home.howItWorksTitle")}</h3>
              <p className="ui-muted home-paragraph">{t("home.howItWorksText")}</p>
            </div>
          </CardHeader>
          <CardContent>
            <ul className="home-checklist">
              {howItWorks.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card className="home-info-card">
          <CardHeader>
            <div className="home-info-card-header">
              <h3>{t("home.videoTipsTitle")}</h3>
              <p className="ui-muted home-paragraph">{t("home.videoTipsText")}</p>
            </div>
          </CardHeader>
          <CardContent>
            <ul className="home-checklist">
              {recordingTips.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <h3>{t("home.latestTitle")}</h3>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="ui-grid">
              <Skeleton />
              <Skeleton />
              <Skeleton />
            </div>
          ) : sessions.length === 0 ? (
            <EmptyState
              title={t("common.empty.noPracticesTitle")}
              description={t("home.emptyDescription")}
              actionLabel={t("home.emptyAction")}
              onAction={() => navigate("/practice")}
            />
          ) : (
            <ul className="session-list">
              {sessions.map((session) => (
                <li key={session.id} className="session-item">
                  <div>
                    <div className="home-session-title">{session.title || t("home.untitled")}</div>
                    <div className="ui-muted">{new Date(session.created_at).toLocaleString()}</div>
                  </div>
                  <div className="ui-row">
                    {session.status === "unknown" ? <span className="ui-muted">{t("common.status.unknown")}</span> : <Badge status={session.status} />}
                    <Link to={`/sessions/${session.id}`}>
                      <Button variant="secondary">{t("common.actions.open")}</Button>
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default HomePage;
