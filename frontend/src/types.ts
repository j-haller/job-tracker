export type AlsoOn = { source: string; url: string | null };

export type Listing = {
  id: string;
  source: string;
  external_id: string;
  title: string;
  company: string | null;
  location: string | null;
  workload: string | null;
  published_at: string | null;
  url: string | null;
  detail_error: string | null;
  first_seen_at: string;
  last_seen_at: string;
  is_active: boolean;
  status: string;
  status_updated_at: string | null;
  note: string | null;
  rating: number | null;
  rated_at: string | null;
  summary: string | null;
  missing_required: number | null;
  is_stale: boolean;
  also_on: AlsoOn[];
};

export type ListingDetail = Listing & {
  description_text: string | null;
  dealbreakers: string[];
};

export type Meta = { status_values: string[] };

export type FetchRun = {
  status: "running" | "ok" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
  found: number | null;
  new: number | null;
  details_ok: number | null;
  details_failed: number | null;
  error: string | null;
};

export type SourceStatus = {
  key: string;
  enabled: boolean;
  config_error: string | null;
  running: boolean;
  interval_minutes: number | null;
  last_run: FetchRun | null;
  next_run_at: string | null;
};

export type Status = {
  sources: SourceStatus[];
  sources_config_error: string | null;
  profile: { present: boolean };
};
