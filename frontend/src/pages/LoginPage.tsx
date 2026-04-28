import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { setToken } from "../api/auth";
import { loginUser } from "../api/user";
import { t } from "../i18n";
import "./LoginPage.css";
import Alert from "../components/ui/Alert";
import Button from "../components/ui/Button";
import { Card, CardContent, CardHeader } from "../components/ui/Card";
import Input from "../components/ui/Input";

const LoginPage = () => {
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
      const data = await loginUser(email, password);
      setToken(data.access_token);
      navigate("/home");
    } catch {
      setError(t("auth.login.invalid"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="auth-page">
      <CardHeader>
        <div>
          <h1>{t("auth.login.title")}</h1>
          <p className="ui-muted">{t("auth.authCardSubtitle")}</p>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="ui-grid">
          <Input label={t("auth.emailLabel")} type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          <Input label={t("auth.passwordLabel")} type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button type="submit" loading={loading}>
            {t("auth.login.submit")}
          </Button>
        </form>
        <p className="ui-muted">
          {t("auth.login.firstTime")} <Link to="/register">{t("auth.login.createAccount")}</Link>.
        </p>
      </CardContent>
    </Card>
  );
};

export default LoginPage;
