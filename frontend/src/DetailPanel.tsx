import { useEffect, useState } from "react";
import { formatDate, formatDateTime } from "./format";
import { RatingBadge } from "./ListingTable";
import StatusSelect from "./StatusSelect";
import type { ListingDetail } from "./types";

type Props = {
  detail: ListingDetail | null;
  error: string | null;
  statusValues: string[];
  saving: boolean;
  onClose: () => void;
  onSave: (id: string, status: string, note?: string | null) => void;
};

function NoteField({ detail, saving, onSave }: Pick<Props, "saving" | "onSave"> & { detail: ListingDetail }) {
  const [note, setNote] = useState(detail.note ?? "");
  useEffect(() => setNote(detail.note ?? ""), [detail.id, detail.note]);
  return (
    <div className="note">
      <label htmlFor="listing-note">Note</label>
      <textarea id="listing-note" rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
      <button
        type="button"
        disabled={saving || note === (detail.note ?? "")}
        onClick={() => onSave(detail.id, detail.status, note.trim() || null)}
      >
        Save note
      </button>
    </div>
  );
}

function Facts({ detail }: { detail: ListingDetail }) {
  const facts = [
    detail.company,
    detail.location,
    detail.workload,
    detail.published_at && `Published ${formatDate(detail.published_at)}`,
    !detail.is_active && "No longer in search results",
  ].filter(Boolean);
  return <p className="facts">{facts.join(" · ")}</p>;
}

function Links({ detail }: { detail: ListingDetail }) {
  return (
    <p className="links">
      {detail.url ? (
        <a href={detail.url} target="_blank" rel="noreferrer">
          Open original
        </a>
      ) : (
        <span className="muted">No link available yet</span>
      )}
      {detail.also_on.map(
        (other) =>
          other.url && (
            <a key={other.source} href={other.url} target="_blank" rel="noreferrer">
              Also on {other.source}
            </a>
          ),
      )}
    </p>
  );
}

function RatingBlock({ detail }: { detail: ListingDetail }) {
  if (detail.rating === null) return <p className="muted">Not rated yet.</p>;
  return (
    <div className="rating-block">
      <RatingBadge rating={detail.rating} isStale={detail.is_stale} />
      <span className="muted">Rated {formatDateTime(detail.rated_at)}</span>
      {detail.summary && <p>{detail.summary}</p>}
    </div>
  );
}

function Description({ detail }: { detail: ListingDetail }) {
  if (detail.description_text) return <div className="description">{detail.description_text}</div>;
  return (
    <p className="muted">
      Description not loaded yet{detail.detail_error ? `: ${detail.detail_error}` : "."}
    </p>
  );
}

export default function DetailPanel({ detail, error, statusValues, saving, onClose, onSave }: Props) {
  return (
    <aside className="detail" aria-label="Listing details">
      <button type="button" className="close" onClick={onClose} aria-label="Close details">
        ×
      </button>
      {error && <p className="banner banner-error">{error}</p>}
      {!detail && !error && <p className="muted">Loading…</p>}
      {detail && (
        <>
          <h2>{detail.title}</h2>
          <Facts detail={detail} />
          <Links detail={detail} />
          <RatingBlock detail={detail} />
          <div className="status-row">
            <span>Status</span>
            <StatusSelect
              label="Status"
              value={detail.status}
              options={statusValues}
              disabled={saving}
              onChange={(status) => onSave(detail.id, status)}
            />
          </div>
          <NoteField detail={detail} saving={saving} onSave={onSave} />
          <h3>Description</h3>
          <Description detail={detail} />
        </>
      )}
    </aside>
  );
}
