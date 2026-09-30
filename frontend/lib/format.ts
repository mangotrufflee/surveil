export function clock(ts?: number | null): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleTimeString("en-GB", { hour12: false });
}

export function stamp(ts?: number | null): string {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  return `${d.toLocaleDateString("en-GB")} ${d.toLocaleTimeString("en-GB", { hour12: false })}`;
}

export function ago(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return "-";
  const s = Math.max(0, seconds);
  if (s < 60) return `${s.toFixed(0)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h`;
  return `${(s / 86400).toFixed(1)}d`;
}

export function pct(v: number, digits = 0): string {
  return `${(v * 100).toFixed(digits)}%`;
}
