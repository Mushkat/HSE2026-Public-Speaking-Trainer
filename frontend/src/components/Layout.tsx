import { Link, Outlet, useNavigate } from "react-router-dom";

import { clearToken, isAuthenticated } from "../api/auth";

const Layout = () => {
  const navigate = useNavigate();
  const authenticated = isAuthenticated();

  const handleLogout = () => {
    clearToken();
    navigate("/login");
  };

  return (
    <div className="app">
      <header className="header">
        <div className="logo">Speech Trainer</div>
        <nav className="nav">
          {authenticated ? (
            <>
              <Link to="/sessions">Sessions</Link>
              <button type="button" onClick={handleLogout} className="link-button">
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login">Login</Link>
              <Link to="/register">Register</Link>
            </>
          )}
        </nav>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
};

export default Layout;
