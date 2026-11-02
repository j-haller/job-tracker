const TIME_ZONE = "Europe/Zurich";

const dateFormat = new Intl.DateTimeFormat("de-CH", {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const dateTimeFormat = new Intl.DateTimeFormat("de-CH", {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDate(value: string | null): string {
  return value ? dateFormat.format(new Date(value)) : "–";
}

export function formatDateTime(value: string | null): string {
  return value ? dateTimeFormat.format(new Date(value)) : "–";
}

export function statusLabel(status: string): string {
  const text = status.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
