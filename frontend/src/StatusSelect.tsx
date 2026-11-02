import { statusLabel } from "./format";

type Props = {
  value: string;
  options: string[];
  disabled: boolean;
  label: string;
  onChange: (status: string) => void;
};

export default function StatusSelect({ value, options, disabled, label, onChange }: Props) {
  return (
    <select
      aria-label={label}
      value={value}
      disabled={disabled}
      onClick={(event) => event.stopPropagation()}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map((option) => (
        <option key={option} value={option}>
          {statusLabel(option)}
        </option>
      ))}
    </select>
  );
}
