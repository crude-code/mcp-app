import { LBL, fmtUSD } from "./valuationUI";

type EconBlock = {
  price: { mode?: string; strip_trade_date?: string | null; oil_deck: number; gas_deck: number; oil_diff: number; gas_diff: number; oil_realized: number; gas_realized: number };
  costs: { opex_var: number; opex_fixed: number; drilling_afe: number; sev_tax_pct: number; gpt_pct: number };
  interest: { type: string; wi_pct?: number; nri_pct?: number; decimal?: number };
  timing: { effective_date: string; horizon_months: number; online_lag: { DUC: number; PUD: number } };
};
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

function Group({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div style={{ background: "var(--bg-panel-mute)", border: "1px solid var(--border-default)", borderRadius: 7, overflow: "hidden" }}>
      <div style={{ ...LBL, fontSize: 9, padding: "9px 13px", borderBottom: "1px solid var(--border-default)" }}>{title}</div>
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "8px 13px", borderTop: "1px solid var(--border-subtle)" }}>
          <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{k}</span>
          <span style={{ fontSize: 12, color: "var(--text-primary)", fontVariantNumeric: "tabular-nums", textAlign: "right" }}>{v}</span>
        </div>
      ))}
    </div>
  );
}

export function EconPanel({ econ }: { econ: EconBlock }) {
  const i = econ.interest;
  const interestVal = i.type === "wi"
    ? `${pct(i.wi_pct ?? 0)} WI · ${pct(i.nri_pct ?? 0)} NRI`
    : `${pct(i.decimal ?? 0)} decimal`;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, padding: "4px 2px" }}>
      <Group title="Price" rows={[
        ["Deck", econ.price.mode === "strip"
          ? `NYMEX strip${econ.price.strip_trade_date ? ` · as of ${econ.price.strip_trade_date}` : ""}`
          : `Flat · WTI $${econ.price.oil_deck.toFixed(2)} · HH $${econ.price.gas_deck.toFixed(2)}`],
        ["Yr-1 avg", `WTI $${econ.price.oil_deck.toFixed(2)} · HH $${econ.price.gas_deck.toFixed(2)}`],
        ["Differentials", `oil ${econ.price.oil_diff} · gas ${econ.price.gas_diff}`],
        ["Realized (yr 1)", `oil $${econ.price.oil_realized.toFixed(2)} · gas $${econ.price.gas_realized.toFixed(2)}`],
      ]} />
      <Group title="Costs" rows={[
        ["Opex — variable", `$${econ.costs.opex_var}/bbl`],
        ["Opex — fixed", `${fmtUSD(econ.costs.opex_fixed)}/well·mo`],
        ["Drilling AFE", fmtUSD(econ.costs.drilling_afe)],
        ["Sev. tax · GPT", `${pct(econ.costs.sev_tax_pct)} · ${pct(econ.costs.gpt_pct)}`],
      ]} />
      <Group title="Interest" rows={[
        ["Type", i.type === "wi" ? "Working interest" : "Minerals"],
        ["Terms", interestVal],
      ]} />
      <Group title="Timing" rows={[
        ["Effective date", econ.timing.effective_date],
        ["Horizon", `${econ.timing.horizon_months} mo`],
        ["Online lag", `DUC +${econ.timing.online_lag.DUC} · PUD +${econ.timing.online_lag.PUD}`],
      ]} />
    </div>
  );
}
