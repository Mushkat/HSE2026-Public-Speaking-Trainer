import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createSession, fetchSessions, Session } from "../api/sessions";

const SessionsPage = () => {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  const loadSessions = async () => {
    setLoading(true);
    try {
      const data = await fetchSessions();
      setSessions(data);
    } catch (err) {
      setError("Failed to load sessions.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSessions();
  }, []);

  const handleCreate = async () => {
    setCreating(true);
    setError("");
    try {
      const session = await createSession(title.trim() || undefined);
      navigate(`/sessions/${session.id}`);
    } catch (err) {
      setError("Failed to create session.");
    } finally {
      setCreating(false);
    }
  };

  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h1>Your sessions</h1>
          <p className="muted">Create a new practice session or revisit an existing one.</p>
        </div>
      </div>
      <div className="session-create">
        <input
          type="text"
          placeholder="Optional session title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <button type="button" className="primary" onClick={handleCreate} disabled={creating}>
          {creating ? "Creating..." : "New session"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {loading ? (
        <p className="muted">Loading sessions...</p>
      ) : sessions.length === 0 ? (
        <p className="muted">No sessions yet. Create your first one.</p>
      ) : (
        <ul className="session-list">
          {sessions.map((session) => (
            <li key={session.id} className="session-item">
              <div>
                <div className="session-title">{session.title || "Untitled session"}</div>
                <div className="muted">Created {new Date(session.created_at).toLocaleString()}</div>
              </div>
              <button type="button" onClick={() => navigate(`/sessions/${session.id}`)}>
                Open
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

export default SessionsPage;
