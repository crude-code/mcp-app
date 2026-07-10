// Crude Code deal sheet — frozen artifact template.
// Paste run_valuation's `data` into DATA at the bottom; write TITLE and TLDR.
// Do not restyle or restructure. Dependencies: react, recharts only.
import { useState } from "react";
import {
  LineChart as ReLineChart, Line, BarChart as ReBarChart, Bar, Cell,
  XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";

// ── Palette — the one object to edit if the user asks for a restyle ─────────
const C = {
  surface: "#ffffff",       // card background
  panelMute: "#f6f7f4",     // header / chart-well background
  border: "#ececea",
  borderSubtle: "#f0f0ee",
  textPrimary: "#0a0a0a",
  textBody: "#374151",
  textMuted: "#4b5563",
  textDim: "#6b7280",
  accent: "#0e7490",        // selected segment / total
  accentFg: "#ffffff",
  up: "#059669",            // oil line, positive cashflow
  down: "#dc2626",          // gas line, capex
  mono: "ui-monospace, SFMono-Regular, Menlo, monospace",
};
const STATUS_DOT = { PDP: C.up, DUC: C.accent, PUD: C.textDim };

const fmtUSD = (usd) => `$${Math.round(usd).toLocaleString("en-US")}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtDate = (d) => {
  const [y, m] = String(d).split("-");
  return `${MONTHS[Number(m) - 1] ?? ""} '${(y ?? "").slice(2)}`;
};
const fmtCompact = (v) => {
  const a = Math.abs(v), sign = v < 0 ? "-" : "";
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${sign}$${Math.round(a / 1e3)}K`;
  return `${sign}$${a}`;
};
const LBL = {
  fontFamily: C.mono, fontSize: 10, letterSpacing: "0.13em",
  textTransform: "uppercase", color: C.textDim, fontWeight: 600,
};

function Segmented({ options, value, onChange, small }) {
  return (
    <div style={{ display: "inline-flex", border: `1px solid ${C.border}`, borderRadius: 6, overflow: "hidden" }}>
      {options.map((opt) => {
        const on = opt === value;
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            style={{
              background: on ? C.accent : C.panelMute,
              color: on ? C.accentFg : C.textMuted,
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

function DealSheet({ title, tldr, data }) {
  const { facts } = data;
  const econ = data.economics;
  const production = data.production; // [{m, date, oil, gas, cashflow}] | null
  const cube = econ.cube;

  // Drop categories with no wells (e.g. zero permitted) — they only add noise.
  const statuses = econ.statuses.filter((s) => s.gross_wells > 0);
  const singleStatus = statuses.length === 1;
  const [deck, setDeck] = useState(econ.default_deck);
  const [rates, setRates] = useState(econ.default_rates);
  const [view, setView] = useState("cash");

  const pv = (code) => cube[deck]?.[code]?.[rates[code]] ?? 0;
  const pvByCode = Object.fromEntries(statuses.map((s) => [s.code, pv(s.code)]));
  const total = statuses.reduce((sum, s) => sum + pvByCode[s.code], 0);
  const share = (code) => (total > 0 ? Math.round((100 * pvByCode[code]) / total) : 0);

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden", fontFamily: "Inter, system-ui, sans-serif" }}>
      {/* EXEC SUMMARY */}
      <div style={{ padding: "18px 20px", borderBottom: `1px solid ${C.border}`, background: C.panelMute }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={LBL}>Valuation · {title}</div>
            <div style={{ marginTop: 8 }}>
              <span style={{ fontSize: 34, fontWeight: 680, color: C.textPrimary, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
                {fmtUSD(total)}
              </span>
              <span style={{ fontSize: 12, color: C.textMuted, marginLeft: 8 }}>total value · net to your interest</span>
            </div>
            <div style={{ marginTop: 4, fontSize: 12, color: C.textMuted }}>
              {statuses.map((s) => `${s.code} ${rates[s.code]}%`).join(" · ")}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ ...LBL, marginBottom: 6 }}>Price deck</div>
            <Segmented options={econ.decks} value={deck} onChange={setDeck} />
          </div>
        </div>

        <div style={{ fontSize: 12.5, color: C.textBody, lineHeight: 1.55, marginTop: 13, maxWidth: 640 }}>
          {tldr}
        </div>

        {/* facts grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 1, marginTop: 16, background: C.border, border: `1px solid ${C.border}`, borderRadius: 7, overflow: "hidden" }}>
          {[["Deal type", facts.deal_type], ["Interest", facts.interest], ["Operator", facts.operator], ["Area", facts.area]].map(([k, v]) => (
            <div key={k} style={{ background: C.surface, padding: "9px 12px" }}>
              <div style={{ ...LBL, fontSize: 8.5 }}>{k}</div>
              <div style={{ fontSize: 13, color: C.textPrimary, marginTop: 3 }}>{v}</div>
            </div>
          ))}
        </div>

        {/* value-share bar — only meaningful when value splits across categories */}
        {!singleStatus && (
          <div style={{ display: "flex", height: 8, borderRadius: 5, overflow: "hidden", marginTop: 14 }}>
            {statuses.map((s) => (
              <div key={s.code} style={{ background: STATUS_DOT[s.code], width: `${share(s.code)}%` }} />
            ))}
          </div>
        )}
      </div>

      {/* PV BY STATUS */}
      <div style={{ padding: "14px 20px" }}>
        <div style={{ ...LBL, marginBottom: 10 }}>PV by status — set the discount rate per category</div>
        <div style={{ display: "grid", gridTemplateColumns: "1.5fr auto .9fr", gap: 10, paddingBottom: 8 }}>
          <span style={{ ...LBL, fontSize: 9 }}>Category</span>
          <span style={{ ...LBL, fontSize: 9, textAlign: "center" }}>Discount rate</span>
          <span style={{ ...LBL, fontSize: 9, textAlign: "right" }}>PV · share</span>
        </div>

        {statuses.map((s) => (
          <div key={s.code} style={{ display: "grid", gridTemplateColumns: "1.5fr auto .9fr", gap: 10, padding: "11px 0", borderTop: `1px solid ${C.borderSubtle}`, alignItems: "center" }}>
            <div>
              <div style={{ color: C.textPrimary, fontSize: 13 }}>
                <span style={{ color: STATUS_DOT[s.code] }}>●</span> {s.label} <span style={{ color: C.textDim, fontSize: 12 }}>{s.tag}</span>
              </div>
              <div style={{ color: C.textDim, fontSize: 12, marginTop: 2 }}>{s.net_wells} net · {s.gross_wells} gross</div>
            </div>
            <Segmented small options={s.rates.map((r) => `${r}%`)} value={`${rates[s.code]}%`}
              onChange={(v) => setRates((prev) => ({ ...prev, [s.code]: v.replace("%", "") }))} />
            <div style={{ textAlign: "right" }}>
              <div style={{ color: C.textPrimary, fontSize: 14, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{fmtUSD(pvByCode[s.code])}</div>
              <div style={{ color: C.textDim, fontSize: 12 }}>{share(s.code)}%</div>
            </div>
          </div>
        ))}

        {/* The lone category IS the total — drop the redundant footer row. */}
        {!singleStatus && (
          <div style={{ display: "grid", gridTemplateColumns: "1.5fr auto .9fr", gap: 10, padding: "11px 0", borderTop: `1px solid ${C.border}`, alignItems: "center" }}>
            <div style={{ color: C.textMuted, fontSize: 12, fontWeight: 600 }}>Total</div>
            <div />
            <div style={{ textAlign: "right", color: C.accent, fontSize: 15, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{fmtUSD(total)}</div>
          </div>
        )}
      </div>

      {/* FORECAST — only when the deal has an active production window */}
      {production && (
        <div style={{ padding: "14px 20px", borderTop: `1px solid ${C.border}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <div style={LBL}>Forecast</div>
            <Segmented small options={["Production", "Net Cashflow"]}
              value={view === "prod" ? "Production" : "Net Cashflow"}
              onChange={(v) => setView(v === "Production" ? "prod" : "cash")} />
          </div>
          <div style={{ color: C.textDim, fontSize: 12, marginBottom: 10 }}>
            {view === "prod" ? (
              <>net oil <span style={{ color: C.up }}>●</span>&nbsp; net gas <span style={{ color: C.down }}>●</span> &nbsp;·&nbsp; volumes per month, independent of the price deck</>
            ) : (
              <><span style={{ color: C.down }}>▮</span> CAPEX&nbsp; <span style={{ color: C.up }}>▮</span> Net Cashflow &nbsp;·&nbsp; net to interest, per month</>
            )}
          </div>
          <div style={{ height: 184, border: `1px solid ${C.border}`, borderRadius: 6, background: C.panelMute, padding: "8px 4px" }}>
            <ResponsiveContainer width="100%" height="100%">
              {view === "prod" ? (
                <ReLineChart data={production} margin={{ top: 8, right: 6, left: 4, bottom: 0 }}>
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: C.textDim }} tickLine={false}
                    axisLine={{ stroke: C.border }} tickFormatter={fmtDate} minTickGap={28} />
                  <YAxis yAxisId="oil" tick={{ fontSize: 9, fill: C.up }} axisLine={false} tickLine={false} width={46}
                    label={{ value: "net oil · bbl", angle: -90, position: "insideLeft", style: { fontSize: 9, fill: C.up, letterSpacing: "0.06em" } }} />
                  <YAxis yAxisId="gas" orientation="right" tick={{ fontSize: 9, fill: C.down }} axisLine={false} tickLine={false} width={46}
                    label={{ value: "net gas · mcf", angle: 90, position: "insideRight", style: { fontSize: 9, fill: C.down, letterSpacing: "0.06em" } }} />
                  <Tooltip contentStyle={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 4, fontSize: 12, color: C.textPrimary }}
                    labelFormatter={(d) => fmtDate(String(d))} />
                  <Line yAxisId="oil" name="net oil (bbl)" type="monotone" dataKey="oil" stroke={C.up} strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line yAxisId="gas" name="net gas (mcf)" type="monotone" dataKey="gas" stroke={C.down} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </ReLineChart>
              ) : (
                <ReBarChart data={production} margin={{ top: 8, right: 6, left: 8, bottom: 0 }}>
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: C.textDim }} tickLine={false}
                    axisLine={{ stroke: C.border }} tickFormatter={fmtDate} minTickGap={28} />
                  <YAxis tick={{ fontSize: 9, fill: C.textDim }} axisLine={false} tickLine={false} width={52} tickFormatter={fmtCompact} />
                  <Tooltip contentStyle={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 4, fontSize: 12, color: C.textPrimary }}
                    labelFormatter={(d) => fmtDate(String(d))} formatter={(v) => [fmtUSD(Number(v)), Number(v) >= 0 ? "Net Cashflow" : "CAPEX"]} />
                  <ReferenceLine y={0} stroke={C.textDim} />
                  <Bar dataKey="cashflow" isAnimationActive={false}>
                    {production.map((p) => (
                      <Cell key={p.m} fill={p.cashflow >= 0 ? C.up : C.down} />
                    ))}
                  </Bar>
                </ReBarChart>
              )}
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Fill these three in. Everything above is frozen. ────────────────────────
const DATA = null;  /* paste run_valuation's `data` object verbatim */
const TITLE = "";   /* short deal title — DATA.facts.area is usually right */
const TLDR = "";    /* 1–2 sentences you write: what the deal is, what drives the value */

export default function App() {
  return <DealSheet title={TITLE} tldr={TLDR} data={DATA} />;
}
