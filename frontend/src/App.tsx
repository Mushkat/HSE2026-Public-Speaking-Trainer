import { Navigate, Route, Routes } from "react-router-dom";

import { isAuthenticated } from "./api/auth";
import AppShell from "./components/layout/AppShell";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import PracticePage from "./pages/PracticePage";
import PublicLandingPage from "./pages/PublicLandingPage";
import RegisterPage from "./pages/RegisterPage";
import SessionDetailsPage from "./pages/SessionDetailsPage";
import UiShowcasePage from "./pages/UiShowcasePage";
import ProgressPage from "./pages/ProgressPage";
import ExercisesPage from "./pages/ExercisesPage";

const App = () => {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={isAuthenticated() ? <Navigate to="/progress" replace /> : <PublicLandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/ui" element={<UiShowcasePage />} />
      </Route>

      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="/home" element={<HomePage />} />
        <Route path="/practice" element={<PracticePage />} />
        <Route path="/progress" element={<ProgressPage />} />
        <Route path="/exercises" element={<ExercisesPage />} />
        <Route path="/sessions/:sessionId" element={<SessionDetailsPage />} />
      </Route>

      <Route path="*" element={<Navigate to={isAuthenticated() ? "/progress" : "/"} replace />} />
    </Routes>
  );
};

export default App;
