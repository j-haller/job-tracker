/** Filtering, sorting and the filter query string. Pure functions, no React. */
import type { Listing } from "./types";

export const DEFAULT_HIDDEN_STATUSES = ["not_interested", "rejected"];

export type Filters = {
  text: string;
  statuses: string[] | null; // null: the default, all except DEFAULT_HIDDEN_STATUSES
  ratingMin: number | null;
  ratingMax: number | null;
  unratedOnly: boolean;
  showInactive: boolean;
  location: string;
  sources: string[] | null; // null: all
};

export const DEFAULT_FILTERS: Filters = {
  text: "",
  statuses: null,
  ratingMin: null,
  ratingMax: null,
  unratedOnly: false,
  showInactive: false,
  location: "",
  sources: null,
};

export type SortColumn =
  | "rating"
  | "missing_required"
  | "title"
  | "company"
  | "source"
  | "location"
  | "workload"
  | "published_at"
  | "first_seen_at"
  | "status";

export type Sort = { column: SortColumn; direction: "asc" | "desc" };

export const DEFAULT_SORT: Sort = { column: "rating", direction: "desc" };

const DESCENDING_FIRST: SortColumn[] = ["rating", "missing_required", "published_at", "first_seen_at"];

export function nextSort(current: Sort, column: SortColumn): Sort {
  if (current.column === column) {
    return { column, direction: current.direction === "asc" ? "desc" : "asc" };
  }
  return { column, direction: DESCENDING_FIRST.includes(column) ? "desc" : "asc" };
}

export function matchesStatus(filters: Filters, status: string): boolean {
  return filters.statuses === null
    ? !DEFAULT_HIDDEN_STATUSES.includes(status)
    : filters.statuses.includes(status);
}

export function applyFilters(rows: Listing[], filters: Filters): Listing[] {
  const text = filters.text.trim().toLowerCase();
  const location = filters.location.trim().toLowerCase();
  return rows.filter((row) => {
    if (!filters.showInactive && !row.is_active) return false;
    if (!matchesStatus(filters, row.status)) return false;
    if (filters.sources !== null && !filters.sources.includes(row.source)) return false;
    if (text && !`${row.title} ${row.company ?? ""}`.toLowerCase().includes(text)) return false;
    if (location && !(row.location ?? "").toLowerCase().includes(location)) return false;
    if (filters.unratedOnly && row.rating !== null) return false;
    if (filters.ratingMin !== null && (row.rating === null || row.rating < filters.ratingMin)) return false;
    if (filters.ratingMax !== null && (row.rating === null || row.rating > filters.ratingMax)) return false;
    return true;
  });
}

const collator = new Intl.Collator("de", { numeric: true, sensitivity: "base" });

function compareValues(a: string | number, b: string | number): number {
  return typeof a === "number" && typeof b === "number" ? a - b : collator.compare(String(a), String(b));
}

/** Empty values always sort last; ties fall back to first seen, newest first. */
export function sortListings(rows: Listing[], sort: Sort, statusValues: string[]): Listing[] {
  const sign = sort.direction === "asc" ? 1 : -1;
  const value = (row: Listing): string | number | null =>
    sort.column === "status" ? statusValues.indexOf(row.status) : row[sort.column];
  return [...rows].sort((a, b) => {
    const [left, right] = [value(a), value(b)];
    if (left === null || right === null) {
      if (left !== right) return left === null ? 1 : -1;
    } else {
      const order = compareValues(left, right);
      if (order !== 0) return sign * order;
    }
    return b.first_seen_at.localeCompare(a.first_seen_at) || a.id.localeCompare(b.id);
  });
}

function parseList(params: URLSearchParams, name: string): string[] | null {
  const value = params.get(name);
  if (value === null) return null;
  return value === "" ? [] : value.split(",");
}

function parseRating(params: URLSearchParams, name: string): number | null {
  const value = params.get(name);
  if (!value) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function parseFilters(search: string): Filters {
  const params = new URLSearchParams(search);
  return {
    text: params.get("q") ?? "",
    statuses: parseList(params, "status"),
    ratingMin: parseRating(params, "min"),
    ratingMax: parseRating(params, "max"),
    unratedOnly: params.get("unrated") === "1",
    showInactive: params.get("inactive") === "1",
    location: params.get("location") ?? "",
    sources: parseList(params, "source"),
  };
}

/** Only non-default values go into the query string. */
export function serializeFilters(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.text) params.set("q", filters.text);
  if (filters.statuses !== null) params.set("status", filters.statuses.join(","));
  if (filters.ratingMin !== null) params.set("min", String(filters.ratingMin));
  if (filters.ratingMax !== null) params.set("max", String(filters.ratingMax));
  if (filters.unratedOnly) params.set("unrated", "1");
  if (filters.showInactive) params.set("inactive", "1");
  if (filters.location) params.set("location", filters.location);
  if (filters.sources !== null) params.set("source", filters.sources.join(","));
  return params.toString();
}
