import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { registerUser } from "../api/user";
import { t } from "../i18n";
import "./RegisterPage.css";
import Alert from "../components/ui/Alert";
import Button from "../components/ui/Button";
import { Card, CardContent, CardHeader } from "../components/ui/Card";
import Input from "../components/ui/Input";

const RegisterPage = () => {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await registerUser(email, password);
      navigate("/login");
    } catch {
      setError(t("auth.register.error"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="auth-page">
      <CardHeader>
        <div>
          <h1>{t("auth.register.title")}</h1>
          <p className="ui-muted">{t("auth.authCardSubtitle")}</p>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="ui-grid">
          <Input label={t("auth.emailLabel")} type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          <Input
            label={t("auth.passwordLabel")}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            minLength={6}
          />
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button type="submit" loading={loading}>
            {t("auth.register.submit")}
          </Button>
        </form>
        <p className="ui-muted">
          {t("auth.register.alreadyHave")} <Link to="/login">{t("auth.login.submit")}</Link>.
        </p>
      </CardContent>
    </Card>
  );
};

export default RegisterPage;
