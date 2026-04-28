import { Link, Outlet, useLocation } from "react-router-dom";

import { isAuthenticated } from "../api/auth";
import { t } from "../i18n";
import "./Layout.css";
import Button from "./ui/Button";

const Layout = () => {
  const authenticated = isAuthenticated();
  const location = useLocation();
  const isAuthPage = ["/login", "/register"].includes(location.pathname);

  return (
    <div className={`public-layout ${isAuthPage ? "public-layout--auth" : ""}`}>
      <header className="public-topbar">
        <Link to="/" className="app-logo-link">
          <span className="app-logo">{t("common.brand")}</span>
        </Link>
        {!isAuthPage ? (
          <nav className="app-nav">
            {authenticated ? (
              <Link to="/home">
                <Button variant="secondary">{t("public.openApp")}</Button>
              </Link>
            ) : (
              <>
                <Link to="/login">
                  <Button variant="ghost">{t("public.login")}</Button>
                </Link>
                <Link to="/register">
                  <Button variant="secondary">{t("public.register")}</Button>
                </Link>
              </>
            )}
            <Link to="/ui">
              <Button variant="ghost">{t("public.uiKit")}</Button>
            </Link>
          </nav>
        ) : null}
      </header>
      <main className="public-content">
        <Outlet />
      </main>
    </div>
  );
};

export default Layout;
