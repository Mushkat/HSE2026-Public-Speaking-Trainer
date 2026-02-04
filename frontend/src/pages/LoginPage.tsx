import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { loginUser } from "../api/user";
import { setToken } from "../api/auth";

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
      navigate("/sessions");
    } catch (err) {
      setError("Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="card">
      <h1>Welcome back</h1>
      <p className="muted">Log in to manage your practice sessions.</p>
      <form onSubmit={handleSubmit} className="form">
        <label className="field">
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <label className="field">
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button type="submit" className="primary" disabled={loading}>
          {loading ? "Signing in..." : "Login"}
        </button>
      </form>
      <p className="muted">
        New here? <Link to="/register">Create an account</Link>.
      </p>
    </section>
  );
};

export default LoginPage;
