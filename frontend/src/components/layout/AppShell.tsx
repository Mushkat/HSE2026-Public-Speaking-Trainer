import { Outlet } from "react-router-dom";

import "./AppShell.css";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import { LLMStatusProvider } from "./LLMStatusContext";

const AppShell = () => {
  return (
    <LLMStatusProvider>
      <div className="shell-root">
        <Sidebar />
        <div className="shell-main-wrap">
          <Topbar />
          <main className="shell-content">
            <Outlet />
          </main>
        </div>
      </div>
    </LLMStatusProvider>
  );
};

export default AppShell;
