import { useState } from "react";
import { LBL, fmtUSD } from "./valuationUI";
import { AssetPanel } from "./AssetPanel";
import { ProductionPanel } from "./ProductionPanel";
import { EconPanel } from "./EconPanel";

type AdvancedBlock = { asset: any; production: any; econ: any };

const TABS = [
  { key: "asset", name: "Asset" },
  { key: "prod", name: "Production" },
  { key: "econ", name: "Econ" },
] as const;

export function AdvancedView({
  advanced, headlineNpv,
}: { advanced: AdvancedBlock; headlineNpv: number }) {
  const [tab, setTab] = useState<string>("asset");
  return (
    <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)", borderRadius: 10, overflow: "hidden" }}>
      <div style={{ padding: "15px 20px 12px", borderBottom: "1px solid var(--border-default)", background: "var(--bg-panel-mute)", display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <div>
          <div style={LBL}>Advanced — Behind the Valuation</div>
          <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}>
            {advanced.asset.operator} · {advanced.asset.area}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ ...LBL, fontSize: 8.5 }}>Total PV</div>
          <div style={{ fontSize: 17, fontWeight: 700, color: "var(--text-primary)", fontVariantNumeric: "tabular-nums" }}>
            {fmtUSD(headlineNpv)}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 2, padding: "0 14px", borderBottom: "1px solid var(--border-default)", background: "var(--bg-panel-mute)" }}>
        {TABS.map((t) => {
          const on = t.key === tab;
          return (
            <button key={t.key} type="button" onClick={() => setTab(t.key)}
              style={{ position: "relative", border: "none", background: "transparent", cursor: "pointer", fontFamily: "inherit",
                padding: "12px 18px 11px", fontSize: 12, fontWeight: 700, letterSpacing: "0.05em",
                color: on ? "var(--text-primary)" : "var(--text-dim)",
                borderBottom: on ? "2px solid var(--content-accent)" : "2px solid transparent" }}>
              {t.name}
            </button>
          );
        })}
      </div>

      <div style={{ padding: "16px 20px 22px", minHeight: 320 }}>
        {tab === "asset" && <AssetPanel asset={advanced.asset} />}
        {tab === "prod" && <ProductionPanel production={advanced.production} />}
        {tab === "econ" && <EconPanel econ={advanced.econ} />}
      </div>
    </div>
  );
}
