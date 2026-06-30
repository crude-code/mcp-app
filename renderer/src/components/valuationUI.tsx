// Shared valuation-widget UI primitives, used by both DealSheet and AdvancedView.
import type { CSSProperties } from "react";

export const fmtUSD = (usd: number) => `$${Math.round(usd).toLocaleString("en-US")}`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// "2029-07" → "Jul '29"
export const fmtDate = (d: string) => {
  const [y, m] = String(d).split("-");
  return `${MONTHS[Number(m) - 1] ?? ""} '${(y ?? "").slice(2)}`;
};

// compact $ for an axis: -559529 → "-$560K", 4.4e6 → "$4.4M"
export const fmtCompact = (v: number) => {
  const a = Math.abs(v), sign = v < 0 ? "-" : "";
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${sign}$${Math.round(a / 1e3)}K`;
  return `${sign}$${a}`;
};

export const LBL: CSSProperties = {
  fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.13em",
  textTransform: "uppercase", color: "var(--text-dim)", fontWeight: 600,
};

export function Segmented({
  options, value, onChange, small,
}: { options: string[]; value: string; onChange: (v: string) => void; small?: boolean }) {
  return (
    <div style={{ display: "inline-flex", border: "1px solid var(--border-default)", borderRadius: 6, overflow: "hidden" }}>
      {options.map((opt) => {
        const on = opt === value;
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            style={{
              background: on ? "var(--content-accent)" : "var(--bg-panel-mute)",
              color: on ? "var(--accent-foreground)" : "var(--text-muted)",
              border: "none", cursor: "pointer", fontFamily: "inherit", fontWeight: 600,
              padding: small ? "3px 8px" : "5px 11px", fontSize: small ? 11 : 12,
            }}
          >
            {opt}
          </button>
        );
      })}
    </div>
  );
}
