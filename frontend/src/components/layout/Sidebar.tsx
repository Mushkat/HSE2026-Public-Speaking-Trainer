import { NavLink } from "react-router-dom";

import { t } from "../../i18n";
import "./Sidebar.css";

const navItems = [
  { to: "/home", label: t("nav.home") },
  { to: "/practice", label: t("nav.practice") },
  { to: "/progress", label: t("nav.progress") },
  { to: "/exercises", label: t("nav.exercises") },
];

const Sidebar = () => {
  return (
    <aside className="shell-sidebar">
      <div className="shell-brand">{t("common.brand")}</div>
      <nav className="shell-nav">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `shell-nav__item ${isActive ? "shell-nav__item--active" : ""}`}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
};

export default Sidebar;
