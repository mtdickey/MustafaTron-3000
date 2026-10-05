// Number and label formatting shared by every page.

/** Win percentage the way sports pages print it: .625, 1.000. */
export function pct(value: number): string {
  const s = value.toFixed(3);
  return s.startsWith("0") ? s.slice(1) : s;
}

export function points(value: number, digits = 1): string {
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function signed(value: number, digits = 1): string {
  const s = Math.abs(value).toFixed(digits);
  return value > 0 ? `+${s}` : value < 0 ? `−${s}` : s;
}

export function record(wins: number, losses: number, ties = 0): string {
  return ties ? `${wins}–${losses}–${ties}` : `${wins}–${losses}`;
}

export function ordinal(n: number): string {
  const teen = n % 100 >= 11 && n % 100 <= 13;
  return `${n}${(!teen && ["th", "st", "nd", "rd"][n % 10]) || "th"}`;
}

export function seasonRange(seasons: number[]): string {
  if (!seasons.length) return "";
  const lo = Math.min(...seasons);
  const hi = Math.max(...seasons);
  return lo === hi ? `${lo}` : `${lo}–${hi}`;
}

// Full color at .250 / .750 by default: real records rarely stray further, and a gentler ramp
// washes out. Pass span 0.5 for an absolute scale, full color only at .000 and 1.000.
function shadeParts(winPct: number, span: number): [hue: string, strength: string] {
  const t = Math.min(1, Math.abs(winPct - 0.5) / span);
  return [winPct >= 0.5 ? "var(--win)" : "var(--loss)", `${Math.round(8 + t * 72)}%`];
}

/**
 * Inline style for a cell shaded by win percentage: orange above .500, lavender below, the
 * colors of the v0 report. The mixing happens in CSS (see .shade in global.css), so the same
 * value reads correctly in light and dark mode. `span` is the distance from .500 that gets full color.
 */
export function shade(winPct: number, span = 0.25): string {
  const [hue, strength] = shadeParts(winPct, span);
  return `--shade: ${hue}; --strength: ${strength}`;
}

/** The color shade() mixes, as a plain CSS value, for cells that switch between two shadings. */
export function shadeColor(winPct: number, span = 0.25): string {
  const [hue, strength] = shadeParts(winPct, span);
  return `color-mix(in oklab, ${hue} ${strength}, var(--surface))`;
}
