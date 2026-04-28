import { useLocation, useNavigate } from "react-router-dom";

import { clearToken } from "../../api/auth";
import { t } from "../../i18n";
import "./Topbar.css";
import Button from "../ui/Button";
import LLMStatusChip from "./LLMStatusChip";

const titleMap: Array<{ match: (path: string) => boolean; title: string }> = [
  { match: (path) => path === "/home", title: t("nav.home") },
  { match: (path) => path === "/practice", title: t("nav.practice") },
  { match: (path) => path === "/progress", title: t("nav.progress") },
  { match: (path) => path.startsWith("/sessions"), title: t("session.detailsTitle") },
];

const Topbar = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const title = titleMap.find((item) => item.match(location.pathname))?.title || t("nav.workspace");

  const handleLogout = () => {
    clearToken();
    navigate("/login");
  };

  return (
    <header className="shell-topbar">
      <div>
        <h1>{title}</h1>
        <p className="ui-muted">{t("nav.workspaceSubtitle")}</p>
      </div>
      <div className="shell-user-menu">
        <LLMStatusChip />
        <div className="shell-user-avatar">U</div>
        <Button variant="secondary" onClick={handleLogout}>
          {t("nav.logout")}
        </Button>
      </div>
    </header>
  );
};

export default Topbar;
