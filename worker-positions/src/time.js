// Time helpers for finviz-positions.
// The Worker runs in UTC; the trade "date" the user experiences is the US/Eastern trading date
// (same convention as the CSV pipeline — .claude/rules/data-pipeline.md § CSV deduplication — and
// the same Intl.DateTimeFormat('America/New_York') approach worker-cron/src/routing.js uses so
// EST/EDT is tracked automatically, no manual DST edit).

// YYYY-MM-DD in US/Eastern for the given instant (default: now).
export function etDateStr(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const g = (t) => parts.find((p) => p.type === t).value;
  return `${g("year")}-${g("month")}-${g("day")}`;
}

// ISO-8601 UTC timestamp for the event ledger.
export function isoUtc(date = new Date()) {
  return date.toISOString();
}
