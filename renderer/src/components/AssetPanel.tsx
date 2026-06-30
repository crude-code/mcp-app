import { LBL } from "./valuationUI";

type Group = { status: string; lateral_band: string; formation: string; n_wells: number };
type AssetBlock = {
  operator: string; area: string; formations: string[];
  groups: Group[]; total_wells: number;
};
const DOT: Record<string, string> = {
  PDP: "var(--change-up)", DUC: "var(--content-accent)", PUD: "var(--text-dim)",
};
const COLS = "1.1fr .8fr 1.2fr .6fr";

export function AssetPanel({ asset }: { asset: AssetBlock }) {
  return (
    <div style={{ padding: "4px 2px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginBottom: 14 }}>
        {[["Operator", asset.operator], ["Area", asset.area], ["Formations", asset.formations.join(" · ")]].map(([k, v]) => (
          <div key={k} style={{ background: "var(--bg-panel-mute)", border: "1px solid var(--border-default)", borderRadius: 7, padding: "9px 12px" }}>
            <div style={{ ...LBL, fontSize: 8.5 }}>{k}</div>
            <div style={{ fontSize: 13, color: "var(--text-primary)", marginTop: 3 }}>{v}</div>
          </div>
        ))}
      </div>
      <div style={{ ...LBL, marginBottom: 8 }}>
        Asset composition — {asset.groups.length} groups across {asset.total_wells} wells
      </div>
      <div style={{ border: "1px solid var(--border-default)", borderRadius: 7, overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: COLS, padding: "8px 14px", background: "var(--bg-panel-mute)", ...LBL, fontSize: 9 }}>
          <span>Status</span><span>Lateral</span><span>Formation</span><span style={{ textAlign: "right" }}>Wells</span>
        </div>
        {asset.groups.map((g, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: COLS, padding: "10px 14px", borderTop: "1px solid var(--border-subtle)", alignItems: "center", fontSize: 12.5 }}>
            <span style={{ color: "var(--text-primary)" }}>
              <span style={{ color: DOT[g.status] ?? "var(--text-dim)" }}>●</span> {g.status}
            </span>
            <span style={{ color: "var(--text-muted)" }}>{g.lateral_band}</span>
            <span style={{ color: "var(--text-muted)" }}>{g.formation}</span>
            <span style={{ textAlign: "right", color: "var(--text-primary)", fontVariantNumeric: "tabular-nums" }}>{g.n_wells}</span>
          </div>
        ))}
        <div style={{ display: "grid", gridTemplateColumns: COLS, padding: "10px 14px", borderTop: "1px solid var(--border-default)", background: "var(--bg-panel-mute)", fontSize: 12.5, fontWeight: 600, color: "var(--text-primary)" }}>
          <span>Total</span><span /><span /><span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{asset.total_wells}</span>
        </div>
      </div>
    </div>
  );
}
