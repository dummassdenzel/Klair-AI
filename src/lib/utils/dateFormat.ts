/** Abbreviated US-style calendar date, e.g. `Nov. 7, 2026`. */
const MONTHS = [
  "Jan.",
  "Feb.",
  "Mar.",
  "Apr.",
  "May",
  "Jun.",
  "Jul.",
  "Aug.",
  "Sep.",
  "Oct.",
  "Nov.",
  "Dec.",
] as const;

export function formatCalendarDate(isoOrDate: string | Date | number): string {
  const d =
    typeof isoOrDate === "string" || typeof isoOrDate === "number"
      ? new Date(isoOrDate)
      : isoOrDate;
  if (Number.isNaN(d.getTime())) return "";
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}
