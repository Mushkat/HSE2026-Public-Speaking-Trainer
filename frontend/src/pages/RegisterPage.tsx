import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { registerUser } from "../api/user";

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
    } catch (err) {
      setError("Registration failed. Try another email.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="card">
      <h1>Create account</h1>
      <p className="muted">Start tracking your speaking sessions.</p>
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
            minLength={6}
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button type="submit" className="primary" disabled={loading}>
          {loading ? "Creating..." : "Register"}
        </button>
      </form>
      <p className="muted">
        Already have an account? <Link to="/login">Log in</Link>.
      </p>
    </section>
  );
};

export default RegisterPage;
