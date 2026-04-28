import { Link } from "react-router-dom";
import { useState } from "react";

import { getI18nValue, t } from "../i18n";
import "./PublicLandingPage.css";
import Button from "../components/ui/Button";
import { Card, CardContent, CardHeader } from "../components/ui/Card";

const PublicLandingPage = () => {
  const howItWorksList = getI18nValue<string[]>("public.howItWorksList");
  const recordingTips = getI18nValue<string[]>("public.recordingTips");
  const [imageError, setImageError] = useState(false);

  return (
    <div className="page-stack">
      <Card className="landing-hero">
        <CardHeader>
          <div className="landing-hero__content">
            <p className="landing-eyebrow">{t("public.eyebrow")}</p>
            <h1>{t("public.heroTitle")}</h1>
            <p className="ui-muted landing-lead">{t("public.heroLead")}</p>
            <div className="ui-row landing-hero-actions">
              <Link to="/login">
                <Button className="landing-main-cta">{t("public.login")}</Button>
              </Link>
              <Link to="/register">
                <Button variant="secondary" className="landing-main-cta">
                  {t("public.register")}
                </Button>
              </Link>
            </div>
          </div>

          <div className="landing-illustration-wrap">
            {imageError ? (
              <div className="landing-illustration-placeholder" role="img" aria-label="Изображение">
                Изображение недоступно
              </div>
            ) : (
              <img
                className="landing-illustration"
                src="/images/landing.jpg"
                alt={t("public.heroTitle")}
                loading="lazy"
                onError={() => setImageError(true)}
              />
            )}
          </div>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <h2>{t("public.howItWorksTitle")}</h2>
        </CardHeader>
        <CardContent>
          <ol className="landing-instruction-list">
            {howItWorksList.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>

          <h3 className="landing-subtitle">{t("public.recordingTitle")}</h3>
          <ul className="landing-tip-list">
            {recordingTips.map((tip) => (
              <li key={tip}>{tip}</li>
            ))}
          </ul>

          <p className="landing-motivation">{t("public.motivation")}</p>
        </CardContent>
      </Card>
    </div>
  );
};

export default PublicLandingPage;
