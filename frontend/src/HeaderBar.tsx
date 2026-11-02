import { formatDateTime } from "./format";
import type { SourceStatus, Status } from "./types";

type Props = {
  status: Status | null;
  statusError: string | null;
  onFetchNow: () => void;
};

function isOverdue(source: SourceStatus): boolean {
  const finished = source.last_run?.finished_at;
  if (!finished || !source.interval_minutes) return false;
  return Date.now() - Date.parse(finished) > 2 * source.interval_minutes * 60_000;
}

function runSummary(source: SourceStatus): string {
  if (source.config_error) return `disabled: ${source.config_error}`;
  if (!source.enabled) return "disabled";
  if (source.running) return "fetching…";
  const run = source.last_run;
  if (!run) return "no fetch yet";
  const time = formatDateTime(run.finished_at ?? run.started_at);
  if (run.status === "failed") return `failed ${time}: ${run.error ?? "unknown error"}`;
  const failed = run.details_failed ? `, ${run.details_failed} details failed` : "";
  return `${run.status} ${time}, ${run.found ?? 0} found, ${run.new ?? 0} new${failed}`;
}

function SourceLine({ source }: { source: SourceStatus }) {
  const bad = !source.running && (Boolean(source.config_error) || source.last_run?.status === "failed" || isOverdue(source));
  return (
    <li className={bad ? "source-line bad" : "source-line"}>
      <strong>{source.key}</strong> {runSummary(source)}
    </li>
  );
}

export default function HeaderBar({ status, statusError, onFetchNow }: Props) {
  const sources = status?.sources ?? [];
  const canFetch = sources.some((source) => source.enabled && !source.running);
  return (
    <header className="header">
      <div className="header-main">
        <h1>Job Tracker</h1>
        <ul className="source-list">
          {sources.map((source) => (
            <SourceLine key={source.key} source={source} />
          ))}
          {status && sources.length === 0 && !status.sources_config_error && (
            <li className="source-line">No sources configured</li>
          )}
        </ul>
        <button type="button" onClick={onFetchNow} disabled={!canFetch}>
          Fetch now
        </button>
      </div>
      {statusError && <p className="banner banner-error">Cannot reach the backend: {statusError}</p>}
      {status?.sources_config_error && <p className="banner banner-error">{status.sources_config_error}</p>}
      {status && !status.profile.present && (
        <p className="banner banner-warning">No skills profile found. Add data/profile.md to enable rating.</p>
      )}
    </header>
  );
}
