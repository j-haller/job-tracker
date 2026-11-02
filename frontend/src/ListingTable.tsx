import { formatDate, formatDateTime } from "./format";
import type { Sort, SortColumn } from "./listings";
import StatusSelect from "./StatusSelect";
import type { Listing } from "./types";

const GOOD_RATING = 70;
const MEDIUM_RATING = 40;

const COLUMNS: { key: SortColumn; label: string }[] = [
  { key: "rating", label: "Rating" },
  { key: "missing_required", label: "Missing" },
  { key: "title", label: "Title" },
  { key: "company", label: "Company" },
  { key: "source", label: "Source" },
  { key: "location", label: "Location" },
  { key: "workload", label: "Workload" },
  { key: "published_at", label: "Published" },
  { key: "first_seen_at", label: "First seen" },
  { key: "status", label: "Status" },
];

type Props = {
  rows: Listing[];
  totalRows: number;
  sort: Sort;
  statusValues: string[];
  selectedId: string | null;
  savingIds: Set<string>;
  lastVisit: number | null;
  onSort: (column: SortColumn) => void;
  onSelect: (id: string) => void;
  onStatusChange: (id: string, status: string) => void;
};

export function RatingBadge({ rating, isStale }: { rating: number | null; isStale: boolean }) {
  if (rating === null) return <span className="badge badge-none">–</span>;
  const level = rating >= GOOD_RATING ? "good" : rating >= MEDIUM_RATING ? "medium" : "low";
  const stale = isStale ? " badge-stale" : "";
  return (
    <span className={`badge badge-${level}${stale}`} title={isStale ? "Profile changed since this rating" : undefined}>
      {rating}
      {isStale && " *"}
    </span>
  );
}

function rowClass(row: Listing, selected: boolean, lastVisit: number | null): string {
  const classes = [];
  if (selected) classes.push("selected");
  if (!row.is_active) classes.push("inactive");
  if (lastVisit !== null && Date.parse(row.first_seen_at) > lastVisit) classes.push("is-new");
  return classes.join(" ");
}

function ariaSort(sort: Sort, column: SortColumn): "ascending" | "descending" | "none" {
  if (sort.column !== column) return "none";
  return sort.direction === "asc" ? "ascending" : "descending";
}

export default function ListingTable(props: Props) {
  const { rows, totalRows, sort, statusValues, selectedId, savingIds, lastVisit } = props;
  if (rows.length === 0) {
    return (
      <p className="empty">
        {totalRows === 0 ? "No listings yet. They appear after the first fetch." : "No listings match the filters."}
      </p>
    );
  }
  return (
    <table className="listings">
      <thead>
        <tr>
          {COLUMNS.map((column) => (
            <th key={column.key} aria-sort={ariaSort(sort, column.key)}>
              <button type="button" onClick={() => props.onSort(column.key)}>
                {column.label}
                {sort.column === column.key && (sort.direction === "asc" ? " ▲" : " ▼")}
              </button>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.id}
            className={rowClass(row, row.id === selectedId, lastVisit)}
            onClick={() => props.onSelect(row.id)}
          >
            <td>
              <RatingBadge rating={row.rating} isStale={row.is_stale} />
            </td>
            <td className="number">{row.missing_required ?? "–"}</td>
            <td className="title-cell">
              <button type="button" className="link" onClick={() => props.onSelect(row.id)}>
                {row.title}
              </button>
            </td>
            <td>{row.company ?? "–"}</td>
            <td>{row.source}</td>
            <td>{row.location ?? "–"}</td>
            <td className="nowrap">{row.workload ?? "–"}</td>
            <td className="nowrap">{formatDate(row.published_at)}</td>
            <td className="nowrap" title={formatDateTime(row.first_seen_at)}>
              {formatDate(row.first_seen_at)}
            </td>
            <td>
              <StatusSelect
                label={`Status of ${row.title}`}
                value={row.status}
                options={statusValues}
                disabled={savingIds.has(row.id)}
                onChange={(status) => props.onStatusChange(row.id, status)}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
