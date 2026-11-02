import { useEffect, useState } from "react";
import { api } from "./api";

type Status = {
  rating_backend: string;
  model: string;
  profile: { present: boolean };
};

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Status>("/status").then(setStatus, (e: Error) => setError(e.message));
  }, []);

  return (
    <main>
      <h1>hello</h1>
      <p>Job Tracker skeleton.</p>
      {error && <p className="error">API error: {error}</p>}
      {status && (
        <p>
          API ok · backend {status.rating_backend} ({status.model}) · profile{" "}
          {status.profile.present ? "present" : "missing"}
        </p>
      )}
    </main>
  );
}
