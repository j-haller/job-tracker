import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import DetailPanel from "./DetailPanel";
import FilterBar from "./FilterBar";
import HeaderBar from "./HeaderBar";
import ListingTable from "./ListingTable";
import {
  applyFilters,
  DEFAULT_SORT,
  nextSort,
  parseFilters,
  serializeFilters,
  sortListings,
  type Filters,
  type Sort,
} from "./listings";
import type { Listing, ListingDetail, Meta, Status } from "./types";

const LAST_VISIT_KEY = "jobtracker.lastVisit";
const STATUS_POLL_MS = 60_000;
const STATUS_POLL_RUNNING_MS = 5_000;
const TOAST_MS = 6_000;

function readLastVisit(): number | null {
  try {
    const value = Number(localStorage.getItem(LAST_VISIT_KEY));
    return value > 0 ? value : null;
  } catch {
    return null;
  }
}

function writeLastVisit(): void {
  try {
    localStorage.setItem(LAST_VISIT_KEY, String(Date.now()));
  } catch {
    // Without storage, nothing is highlighted as new.
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function listingPath(id: string): string {
  return `/listings/${encodeURIComponent(id)}`;
}

export default function App() {
  const [statusValues, setStatusValues] = useState<string[]>([]);
  const [listings, setListings] = useState<Listing[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(() => parseFilters(window.location.search));
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ListingDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [savingIds, setSavingIds] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<string | null>(null);
  const [lastVisit] = useState<number | null>(readLastVisit);
  const finishedMarker = useRef<string | null>(null);

  const loadListings = useCallback(async () => {
    try {
      setListings(await api<Listing[]>("/listings"));
      setListError(null);
    } catch (error) {
      setListError(message(error));
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await api<Status>("/status");
      setStatus(next);
      setStatusError(null);
      const marker = next.sources.map((source) => source.last_run?.finished_at ?? "").join("|");
      if (finishedMarker.current !== null && finishedMarker.current !== marker) void loadListings();
      finishedMarker.current = marker;
    } catch (error) {
      setStatusError(message(error));
    }
  }, [loadListings]);

  useEffect(() => {
    writeLastVisit();
    api<Meta>("/meta").then(
      (meta) => setStatusValues(meta.status_values),
      (error) => setListError(message(error)),
    );
    void loadListings();
  }, [loadListings]);

  const anyRunning = status?.sources.some((source) => source.running) ?? false;
  useEffect(() => {
    void refreshStatus();
    const timer = setInterval(refreshStatus, anyRunning ? STATUS_POLL_RUNNING_MS : STATUS_POLL_MS);
    return () => clearInterval(timer);
  }, [anyRunning, refreshStatus]);

  useEffect(() => {
    const query = serializeFilters(filters);
    window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }, [filters]);

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    if (selectedId === null) return;
    let stale = false;
    api<ListingDetail>(listingPath(selectedId)).then(
      (loaded) => {
        if (!stale) setDetail(loaded);
      },
      (error) => {
        if (!stale) setDetailError(message(error));
      },
    );
    return () => {
      stale = true;
    };
  }, [selectedId]);

  useEffect(() => {
    if (toast === null) return;
    const timer = setTimeout(() => setToast(null), TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  const sources = useMemo(() => [...new Set(listings.map((row) => row.source))].sort(), [listings]);
  const visible = useMemo(
    () => sortListings(applyFilters(listings, filters), sort, statusValues),
    [listings, filters, sort, statusValues],
  );

  const patchListing = (id: string, changes: Partial<ListingDetail>) => {
    setListings((rows) => rows.map((row) => (row.id === id ? { ...row, ...changes } : row)));
    setDetail((current) => (current?.id === id ? { ...current, ...changes } : current));
  };

  const setSaving = (id: string, saving: boolean) =>
    setSavingIds((current) => {
      const next = new Set(current);
      if (saving) next.add(id);
      else next.delete(id);
      return next;
    });

  /** The status shows at once and rolls back if the save fails. A missing note stays unchanged. */
  const saveListing = async (id: string, nextStatus: string, note?: string | null) => {
    const previous = listings.find((row) => row.id === id)?.status ?? detail?.status;
    setSaving(id, true);
    patchListing(id, { status: nextStatus });
    try {
      const body = note === undefined ? { status: nextStatus } : { status: nextStatus, note };
      const saved = await api<ListingDetail>(`${listingPath(id)}/status`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      patchListing(id, { status: saved.status, note: saved.note, status_updated_at: saved.status_updated_at });
    } catch (error) {
      if (previous) patchListing(id, { status: previous });
      setToast(`Could not save: ${message(error)}`);
    } finally {
      setSaving(id, false);
    }
  };

  const fetchNow = async () => {
    try {
      await api("/fetch", { method: "POST" });
    } catch (error) {
      setToast(`Could not start fetch: ${message(error)}`);
    }
    await refreshStatus();
  };

  return (
    <div className={selectedId ? "app with-detail" : "app"}>
      <HeaderBar status={status} statusError={statusError} onFetchNow={fetchNow} />
      <FilterBar
        filters={filters}
        statusValues={statusValues}
        sources={sources}
        shown={visible.length}
        total={listings.length}
        onChange={setFilters}
      />
      {listError && <p className="banner banner-error">Cannot load listings: {listError}</p>}
      <main className="content">
        <div className="table-scroll">
          <ListingTable
            rows={visible}
            totalRows={listings.length}
            sort={sort}
            statusValues={statusValues}
            selectedId={selectedId}
            savingIds={savingIds}
            lastVisit={lastVisit}
            onSort={(column) => setSort((current) => nextSort(current, column))}
            onSelect={setSelectedId}
            onStatusChange={saveListing}
          />
        </div>
        {selectedId && (
          <DetailPanel
            detail={detail}
            error={detailError}
            statusValues={statusValues}
            saving={savingIds.has(selectedId)}
            onClose={() => setSelectedId(null)}
            onSave={saveListing}
          />
        )}
      </main>
      {toast && (
        <div className="toast" role="alert">
          {toast}
        </div>
      )}
    </div>
  );
}
