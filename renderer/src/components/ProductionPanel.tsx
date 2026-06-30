import { useState } from "react";
import { LineChart as ReLineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import { LBL, fmtDate } from "./valuationUI";

type SeriesPoint = { date: string; oil: number; gas: number; actual: boolean };
type Estimate = {
  key: string; name: string; kind: "history" | "cohort"; series: SeriesPoint[];
  meta: { analogs: number | null; wells: number; radius_mi: number | null; b_median: number | null; basis: string };
  analog_wells?: { api: string; operator?: string; formation?: string; lateral_ft?: number }[];
};
type ProductionBlock = { now_date: string; estimates: Estimate[] };
const nowLabel = (d: string) => d.slice(0, 7);

export function ProductionPanel({ production }: { production: ProductionBlock }) {
  const [sel, setSel] = useState(production.estimates[0]?.key);
  const [showAnalogs, setShowAnalogs] = useState(false);
  const est = production.estimates.find((e) => e.key === sel) ?? production.estimates[0];
  if (!est) return null;
  // The analog cohort is a pure type-curve shape — it has nothing to do with calendar
  // timing, so it's plotted against month index (0,1,2,…). PDP carries real history +
  // forecast, so it stays on calendar dates with a NOW marker at the actual→forecast handoff.
  const isCohort = est.kind === "cohort";
  // Split into solid (actual) and dashed (forecast) by nulling the other on each row.
  const data = est.series.map((p, i) => ({
    x: isCohort ? i : p.date, actual: p.actual ? p.oil : null, forecast: p.actual ? null : p.oil,
  }));

  return (
    <div style={{ padding: "4px 2px" }}>
      <div style={{ ...LBL, marginBottom: 8 }}>Estimates — select to verify</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginBottom: 10 }}>
        {production.estimates.map((e) => {
          const on = e.key === sel;
          return (
            <button key={e.key} type="button" onClick={() => { setSel(e.key); setShowAnalogs(false); }}
              style={{ border: `1px solid ${on ? "var(--content-accent)" : "var(--border-default)"}`, borderRadius: 5,
                background: on ? "var(--bg-surface)" : "var(--bg-panel-mute)", cursor: "pointer", fontFamily: "inherit",
                fontSize: 11, color: on ? "var(--text-primary)" : "var(--text-muted)", padding: "6px 10px" }}>
              {e.name} <span style={{ color: "var(--text-dim)" }}>{e.meta.wells}</span>
            </button>
          );
        })}
      </div>

      <div style={{ height: 200, border: "1px solid var(--border-default)", borderRadius: 6, background: "var(--bg-panel-mute)", padding: "8px 4px" }}>
        <ResponsiveContainer width="100%" height="100%">
          <ReLineChart data={data} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
            <XAxis dataKey="x" type={isCohort ? "number" : "category"}
              tick={{ fontSize: 9, fill: "var(--text-dim)" }} tickLine={false}
              axisLine={{ stroke: "var(--border-default)" }}
              tickFormatter={isCohort ? undefined : (d) => fmtDate(String(d))} minTickGap={28} />
            <YAxis tick={{ fontSize: 9, fill: "var(--text-dim)" }} axisLine={false} tickLine={false} width={46} />
            <Tooltip contentStyle={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)", borderRadius: 4, fontSize: 12 }}
              labelFormatter={(d) => (isCohort ? `Month ${d}` : fmtDate(String(d)))} />
            {!isCohort && (
              <ReferenceLine x={nowLabel(production.now_date)} stroke="var(--text-dim)" strokeDasharray="4 4"
                label={{ value: "NOW", fontSize: 9, fill: "var(--text-dim)" }} />
            )}
            <Line type="monotone" dataKey="actual" stroke="var(--change-up)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            <Line type="monotone" dataKey="forecast" stroke="var(--change-up)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} connectNulls />
          </ReLineChart>
        </ResponsiveContainer>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(96px,1fr))", gap: 10, marginTop: 12, borderTop: "1px solid var(--border-subtle)", paddingTop: 11 }}>
        {([["Analogs", est.meta.analogs ?? "—"], ["Wells", est.meta.wells], ["Radius", est.meta.radius_mi ? `~${est.meta.radius_mi} mi` : "—"], ["b (median)", est.meta.b_median ?? "—"], ["Basis", est.meta.basis]] as [string, string | number][]).map(([k, v]) => (
          <div key={k}>
            <div style={{ ...LBL, fontSize: 8.5 }}>{k}</div>
            <div style={{ fontSize: 12.5, color: "var(--text-primary)", marginTop: 3 }}>{v}</div>
          </div>
        ))}
      </div>

      {est.kind === "cohort" && est.analog_wells && est.analog_wells.length > 0 && (
        <div style={{ marginTop: 11 }}>
          <button type="button" onClick={() => setShowAnalogs((s) => !s)}
            style={{ background: "none", border: "none", cursor: "pointer", fontFamily: "inherit", fontSize: 11, color: "var(--content-accent)", padding: 0 }}>
            {showAnalogs ? "▾ hide" : "▸ show"} the {est.analog_wells.length} analog wells
          </button>
          {showAnalogs && (
            <div style={{ marginTop: 8, maxHeight: 160, overflowY: "auto", border: "1px solid var(--border-subtle)", borderRadius: 6 }}>
              {est.analog_wells.map((w) => (
                <div key={w.api} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "6px 11px", borderTop: "1px solid var(--border-subtle)", fontSize: 11.5, color: "var(--text-muted)" }}>
                  <span style={{ color: "var(--text-primary)" }}>{w.api}</span>
                  <span>{w.operator ?? "—"} · {w.formation ?? "—"} · {w.lateral_ft ? `${Math.round(w.lateral_ft)}'` : "—"}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
