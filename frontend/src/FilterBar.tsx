import { useEffect, useRef } from "react";
import { statusLabel } from "./format";
import { DEFAULT_FILTERS, matchesStatus, type Filters } from "./listings";

type Props = {
  filters: Filters;
  statusValues: string[];
  sources: string[];
  shown: number;
  total: number;
  onChange: (filters: Filters) => void;
};

type MultiSelectProps = {
  label: string;
  options: string[];
  selected: string[];
  optionLabel?: (option: string) => string;
  onChange: (selected: string[]) => void;
};

function MultiSelect({ label, options, selected, optionLabel, onChange }: MultiSelectProps) {
  const root = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) root.current.open = false;
    };
    document.addEventListener("click", closeOnOutsideClick);
    return () => document.removeEventListener("click", closeOnOutsideClick);
  }, []);
  const toggle = (option: string, checked: boolean) =>
    onChange(checked ? options.filter((o) => o === option || selected.includes(o)) : selected.filter((o) => o !== option));
  return (
    <details className="multi-select" ref={root}>
      <summary>
        {label} ({selected.length}/{options.length})
      </summary>
      <div className="multi-select-options">
        {options.map((option) => (
          <label key={option}>
            <input
              type="checkbox"
              checked={selected.includes(option)}
              onChange={(event) => toggle(option, event.target.checked)}
            />
            {optionLabel ? optionLabel(option) : option}
          </label>
        ))}
      </div>
    </details>
  );
}

function ratingValue(text: string): number | null {
  return text === "" ? null : Number(text);
}

export default function FilterBar({ filters, statusValues, sources, shown, total, onChange }: Props) {
  const set = (changes: Partial<Filters>) => onChange({ ...filters, ...changes });
  return (
    <section className="filters" aria-label="Filters">
      <label className="field field-wide">
        Search
        <input
          type="search"
          placeholder="Title or company"
          value={filters.text}
          onChange={(event) => set({ text: event.target.value })}
        />
      </label>
      <label className="field">
        Location
        <input type="search" value={filters.location} onChange={(event) => set({ location: event.target.value })} />
      </label>
      <MultiSelect
        label="Status"
        options={statusValues}
        selected={statusValues.filter((status) => matchesStatus(filters, status))}
        optionLabel={statusLabel}
        onChange={(statuses) => set({ statuses })}
      />
      <MultiSelect
        label="Source"
        options={sources}
        selected={filters.sources === null ? sources : sources.filter((source) => filters.sources?.includes(source))}
        onChange={(selected) => set({ sources: selected })}
      />
      <label className="field field-number">
        Rating min
        <input
          type="number"
          min={1}
          max={100}
          value={filters.ratingMin ?? ""}
          onChange={(event) => set({ ratingMin: ratingValue(event.target.value) })}
        />
      </label>
      <label className="field field-number">
        Rating max
        <input
          type="number"
          min={1}
          max={100}
          value={filters.ratingMax ?? ""}
          onChange={(event) => set({ ratingMax: ratingValue(event.target.value) })}
        />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={filters.unratedOnly}
          onChange={(event) => set({ unratedOnly: event.target.checked })}
        />
        Unrated only
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={filters.showInactive}
          onChange={(event) => set({ showInactive: event.target.checked })}
        />
        Show inactive
      </label>
      <button type="button" onClick={() => onChange(DEFAULT_FILTERS)}>
        Reset
      </button>
      <span className="count">
        {shown} of {total}
      </span>
    </section>
  );
}
