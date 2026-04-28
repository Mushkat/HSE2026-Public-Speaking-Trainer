import { t } from "../i18n";
import exercises from "../data/exercises.ru.json";
import "./ExercisesPage.css";
import { Card, CardContent, CardHeader } from "../components/ui/Card";

type ExerciseItem = { id: string; title: string; platform: string; url: string; tags?: string[] };

const ExercisesPage = () => {
  const items = exercises as ExerciseItem[];

  return (
    <Card>
      <CardHeader>
        <div>
          <h1>{t("exercises.title")}</h1>
          <p className="ui-muted">{t("exercises.intro")}</p>
        </div>
      </CardHeader>
      <CardContent>
        <div className="exercises-grid">
          {items.map((item) => (
            <article key={item.id} className="exercises-card">
              <h3>{item.title}</h3>
              <p className="ui-muted exercises-platform">Платформа: {item.platform}</p>
              <div className="exercises-tags">
                {(item.tags || []).map((tag) => (
                  <span key={`${item.id}-${tag}`} className="exercises-tag">{tag}</span>
                ))}
              </div>
              <a className="exercises-link" href={item.url} target="_blank" rel="noreferrer">
                Смотреть
              </a>
            </article>
          ))}
        </div>
      </CardContent>
    </Card>
  );
};

export default ExercisesPage;
