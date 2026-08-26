// Crude Code ARIES explorer — frozen artifact template.
// Paste aries_payload.py's output into DATA at the bottom; write TITLE and
// TLDR. Do not restyle or restructure. Dependencies: react only.
//
// The viewer is the cover page of one ARIES database: what it holds, whose
// scenario is decoded, where the forecasts come from, the assumptions the
// seller ran, and whether the database is internally consistent. It is
// data-driven: every module renders only when the payload carries its data.
// Every number is a deterministic rollup computed by aries_payload.py —
// nothing here or in the fill step does arithmetic.
import { useState } from "react";

// ── Palette — matches the deal-sheet / dataroom / checkup templates. ────────
const C = {
  surface: "#ffffff",
  panelMute: "#f6f7f4",
  border: "#ececea",
  borderSubtle: "#f0f0ee",
  textPrimary: "#0a0a0a",
  textBody: "#374151",
  textMuted: "#4b5563",
  textDim: "#6b7280",
  accent: "#0e7490",
  accentSoft: "#e6f2f5",
  flag: "#b45309",
  flagBg: "#fdf7ef",
  ok: "#2f7d4a",
  okSoft: "#eef6f0",
  barTrack: "#e8e9e6",
  neutralBar: "#9ca3af",
  mono: "ui-monospace, SFMono-Regular, Menlo, monospace",
};
const LBL = {
  fontFamily: C.mono, fontSize: 10, letterSpacing: "0.13em",
  textTransform: "uppercase", color: C.textDim, fontWeight: 600,
};
const TILE_K = { ...LBL, fontSize: 8.5 };
const TH = { ...LBL, fontSize: 8.5, textAlign: "right", padding: "4px 8px", whiteSpace: "nowrap" };
const TD = { padding: "5px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textBody, whiteSpace: "nowrap" };
const SEG_COLORS = [C.accent, C.ok, C.flag, C.neutralBar, C.textDim, C.textPrimary];

const fmtInt = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-US"));
const fmtBytes = (b) => (b == null ? "—" : b >= 1 << 20 ? `${(b / (1 << 20)).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`);
// Full precision on interest decimals — they are the multiplier on every
// dollar; rounding here would make the viewer disagree with the database.
const fmtDecimal = (v) => (v == null ? "—" : String(v));

function StatTiles({ tiles }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(tiles.length, 6)},1fr)`, gap: 1, background: C.border, border: `1px solid ${C.border}`, borderRadius: 7, overflow: "hidden" }}>
      {tiles.map(([k, v, n]) => (
        <div key={k} style={{ background: C.surface, padding: "8px 10px" }}>
          <div style={TILE_K}>{k}</div>
          <div style={{ fontSize: 16, fontWeight: 650, color: C.textPrimary, marginTop: 2, fontVariantNumeric: "tabular-nums" }}>{v}</div>
          {n ? <div style={{ fontSize: 10, color: C.textDim }}>{n}</div> : null}
        </div>
      ))}
    </div>
  );
}

// ── Reserve categories — one bar of the case list ────────────────────────────
function RescatBar({ rollup }) {
  const total = rollup.reduce((s, r) => s + r.count, 0) || 1;
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 8 }}>Reserve categories · {fmtInt(total)} properties</div>
      <div style={{ display: "flex", height: 18, borderRadius: 5, overflow: "hidden", border: `1px solid ${C.border}` }}>
        {rollup.map((r, i) => (
          <div key={r.rescat} style={{ width: `${Math.max(1.5, (100 * r.count) / total)}%`, background: SEG_COLORS[i % SEG_COLORS.length] }} title={`${r.rescat}: ${r.count}`} />
        ))}
      </div>
      <div style={{ display: "flex", gap: 18, marginTop: 5, flexWrap: "wrap" }}>
        {rollup.map((r, i) => (
          <span key={r.rescat} style={{ fontSize: 11.5, color: C.textMuted, display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: SEG_COLORS[i % SEG_COLORS.length], display: "inline-block" }} />
            {r.rescat} {fmtInt(r.count)} · {fmtInt(r.with_production)} producing · {fmtInt(r.with_forecast)} forecast
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Scenario qualifiers + forecast sources, side by side ────────────────────
function ScenarioAndSources({ scenarios, forecastMix }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 28px" }}>
      {scenarios?.qualifiers?.length ? (
        <div style={{ minWidth: 0 }}>
          <div style={{ ...LBL, marginBottom: 6 }}>Scenario qualifiers</div>
          {scenarios.qualifiers.map((q) => (
            <div key={q.name} style={{ display: "flex", gap: 8, alignItems: "baseline", padding: "2px 0", fontSize: 12 }}>
              <span style={{ fontFamily: C.mono, fontWeight: 650, color: q.name === scenarios.chosen ? C.accent : C.textBody }}>{q.name}</span>
              {q.name === scenarios.chosen ? (
                <span style={{ fontFamily: C.mono, fontSize: 8.5, letterSpacing: "0.08em", textTransform: "uppercase", color: C.accent, border: `1px solid ${C.accent}`, borderRadius: 4, padding: "1px 5px" }}>decoded</span>
              ) : null}
              <span style={{ fontSize: 11, color: C.textDim }}>{fmtInt(q.lines)} lines · {fmtInt(q.properties)} properties</span>
            </div>
          ))}
        </div>
      ) : null}
      {forecastMix?.length ? (
        <div style={{ minWidth: 0 }}>
          <div style={{ ...LBL, marginBottom: 6 }}>Where the forecasts come from</div>
          {forecastMix.map((f) => (
            <div key={f.source} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "2px 0", fontSize: 12 }}>
              <span style={{ color: f.source === "none" ? C.flag : C.textBody }}>{f.source}</span>
              <span style={{ color: C.textDim, fontVariantNumeric: "tabular-nums" }}>{fmtInt(f.count)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ── Integrity — does the database agree with itself ─────────────────────────
function Integrity({ checks }) {
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 8 }}>Internal consistency</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {checks.map((c, i) => (
          <div key={i} style={{ display: "flex", gap: 10, padding: "6px 10px", background: c.ok ? C.okSoft : C.flagBg, border: `1px solid ${C.borderSubtle}`, borderRadius: 7 }}>
            <span style={{ fontFamily: C.mono, fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: c.ok ? C.ok : C.flag, fontWeight: 700, flex: "none", width: 88, paddingTop: 1 }}>{c.ok ? "✓ checks" : "needs a look"}</span>
            <div style={{ fontSize: 12, color: C.textBody, lineHeight: 1.45 }}>
              <span style={{ fontWeight: 600, color: C.textPrimary }}>{c.label}</span>
              <span style={{ color: C.textMuted }}> — {c.detail}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── The property manifest, grouped by reserve category ──────────────────────
function PropertyGroups({ properties, truncated }) {
  const groups = [];
  for (const p of properties) {
    const g = groups.find((x) => x.rescat === p.rescat);
    if (g) g.rows.push(p);
    else groups.push({ rescat: p.rescat, rows: [p] });
  }
  const [open, setOpen] = useState(() => (groups.length ? { [groups[0].rescat]: true } : {}));
  const hasProd = properties.some((p) => p.prod_months);
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 6 }}>Properties · decoded scenario</div>
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflow: "hidden" }}>
        {groups.map((g, gi) => (
          <div key={g.rescat} style={{ borderTop: gi ? `1px solid ${C.border}` : "none" }}>
            <div onClick={() => setOpen((o) => ({ ...o, [g.rescat]: !o[g.rescat] }))}
              style={{ cursor: "pointer", display: "flex", gap: 8, alignItems: "baseline", padding: "7px 10px", background: C.panelMute }}>
              <span style={{ color: C.accent, fontFamily: C.mono, fontSize: 11 }}>{open[g.rescat] ? "▾" : "▸"}</span>
              <span style={{ fontFamily: C.mono, fontSize: 11, fontWeight: 700, color: C.textPrimary }}>{g.rescat}</span>
              <span style={{ fontSize: 11, color: C.textDim }}>{g.rows.length} propert{g.rows.length === 1 ? "y" : "ies"}</span>
            </div>
            {open[g.rescat] ? (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
                  <thead>
                    <tr>
                      <th style={{ ...TH, textAlign: "left" }}>Case</th>
                      <th style={{ ...TH, textAlign: "left" }}>API</th>
                      <th style={{ ...TH, textAlign: "left" }}>County, St</th>
                      <th style={TH}>Major</th>
                      <th style={TH}>Lateral ft</th>
                      <th style={TH}>WI</th>
                      <th style={TH}>NRI</th>
                      {hasProd ? <th style={TH}>Prod months</th> : null}
                      {hasProd ? <th style={TH}>Cum oil bbl</th> : null}
                      {hasProd ? <th style={TH}>Cum gas MCF</th> : null}
                      <th style={{ ...TH, textAlign: "left" }}>Forecast</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.rows.map((p, i) => (
                      <tr key={p.propnum || i} style={{ borderTop: `1px solid ${C.borderSubtle}` }}>
                        <td style={{ ...TD, textAlign: "left" }}>
                          <span style={{ fontWeight: 550, color: C.textPrimary }}>{p.name}</span>
                          {p.operator ? <span style={{ fontSize: 10, color: C.textDim, marginLeft: 6 }}>{p.operator}</span> : null}
                        </td>
                        <td style={{ ...TD, textAlign: "left", fontFamily: C.mono, fontSize: 10.5, color: p.api ? C.textMuted : C.textDim }}>{p.api || "—"}</td>
                        <td style={{ ...TD, textAlign: "left", color: C.textMuted }}>{[p.county, p.state].filter(Boolean).join(", ") || "—"}</td>
                        <td style={{ ...TD, color: C.textMuted }}>{p.major || "—"}</td>
                        <td style={TD}>{fmtInt(p.lateral_ft)}</td>
                        <td style={{ ...TD, fontFamily: C.mono, fontSize: 10.5 }}>{fmtDecimal(p.wi)}</td>
                        <td style={{ ...TD, fontFamily: C.mono, fontSize: 10.5 }}>{fmtDecimal(p.nri)}</td>
                        {hasProd ? <td style={TD}>{p.prod_months ? `${p.prod_months}${p.last_prod ? ` · thru ${p.last_prod}` : ""}` : "—"}</td> : null}
                        {hasProd ? <td style={TD}>{fmtInt(p.cum_oil)}</td> : null}
                        {hasProd ? <td style={TD}>{fmtInt(p.cum_gas)}</td> : null}
                        <td style={{ ...TD, textAlign: "left", color: p.forecast === "none" ? C.flag : C.textMuted, fontSize: 11 }}>{p.forecast}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        ))}
      </div>
      {truncated ? (
        <div style={{ fontSize: 10.5, color: C.flag, marginTop: 5 }}>
          Showing the first {fmtInt(truncated.shown)} of {fmtInt(truncated.total)} properties — the rollups above cover all of them.
        </div>
      ) : null}
    </div>
  );
}

// ── The assumptions the seller ran, clustered across properties ─────────────
function Assumptions({ clusters, truncated }) {
  const sections = [];
  for (const c of clusters) {
    const s = sections.find((x) => x.section === c.section);
    if (s) s.rows.push(c);
    else sections.push({ section: c.section, name: c.section_name, rows: [c] });
  }
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 6 }}>Economic assumptions · identical lines clustered across properties</div>
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
          <tbody>
            {sections.map((s) => (
              [<tr key={`s${s.section}`}>
                <td colSpan={3} style={{ ...LBL, fontSize: 8.5, padding: "7px 8px 3px", background: C.panelMute }}>{s.name}</td>
              </tr>,
              ...s.rows.map((c, i) => (
                <tr key={`s${s.section}-${i}`} style={{ borderTop: `1px solid ${C.borderSubtle}` }}>
                  <td style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>
                    <span style={{ fontFamily: C.mono, fontSize: 10.5, color: C.accent }}>{c.keyword}</span>
                    {c.label ? <span style={{ fontSize: 11, color: C.textMuted, marginLeft: 7 }}>{c.label}</span> : null}
                  </td>
                  <td style={{ padding: "4px 8px", fontFamily: C.mono, fontSize: 10.5, color: C.textBody }}>{c.expression}</td>
                  <td style={{ padding: "4px 8px", textAlign: "right", fontSize: 10.5, color: C.textDim, whiteSpace: "nowrap" }}>{fmtInt(c.properties)} props</td>
                </tr>
              ))]
            ))}
          </tbody>
        </table>
      </div>
      {truncated ? (
        <div style={{ fontSize: 10.5, color: C.flag, marginTop: 5 }}>
          Showing {fmtInt(truncated.shown)} of {fmtInt(truncated.total)} distinct assumption lines.
        </div>
      ) : null}
    </div>
  );
}

// ── Lookup tables — type curves, price decks, tax schedules ─────────────────
function Lookups({ lookups, truncated }) {
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 8 }}>Lookup tables · type curves, price decks, schedules</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {lookups.map((lk) => (
          <div key={lk.name} style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflow: "hidden" }}>
            <div style={{ padding: "6px 10px", background: C.panelMute, display: "flex", gap: 10, alignItems: "baseline" }}>
              <span style={{ fontFamily: C.mono, fontSize: 11.5, fontWeight: 700, color: C.textPrimary }}>{lk.name}</span>
              <span style={{ fontSize: 10.5, color: C.textDim }}>{fmtInt(lk.rows_total)} data rows</span>
            </div>
            {lk.template?.length ? (
              <div style={{ padding: "6px 10px", borderTop: `1px solid ${C.borderSubtle}` }}>
                <div style={{ ...TILE_K, marginBottom: 3 }}>Template — the forecast shape each row fills</div>
                {lk.template.map((t, i) => (
                  <div key={i} style={{ fontFamily: C.mono, fontSize: 10.5, color: C.textBody, whiteSpace: "pre-wrap" }}>{t}</div>
                ))}
              </div>
            ) : null}
            {lk.rows?.length ? (
              <div style={{ overflowX: "auto", borderTop: `1px solid ${C.borderSubtle}` }}>
                <table style={{ borderCollapse: "collapse", fontSize: 10.5, fontFamily: C.mono, minWidth: "50%" }}>
                  {lk.header?.length ? (
                    <thead><tr>{lk.header.map((h, i) => <th key={i} style={{ ...TH, textAlign: "left" }}>{h}</th>)}</tr></thead>
                  ) : null}
                  <tbody>
                    {lk.rows.map((r, i) => (
                      <tr key={i} style={{ borderTop: `1px solid ${C.borderSubtle}` }}>
                        {r.map((v, j) => <td key={j} style={{ padding: "3px 8px", color: C.textBody, whiteSpace: "nowrap" }}>{v}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {lk.rows_total > lk.rows.length ? (
                  <div style={{ fontSize: 10, color: C.flag, padding: "3px 8px" }}>first {lk.rows.length} of {fmtInt(lk.rows_total)} rows</div>
                ) : null}
              </div>
            ) : null}
          </div>
        ))}
      </div>
      {truncated ? (
        <div style={{ fontSize: 10.5, color: C.flag, marginTop: 5 }}>
          Showing {fmtInt(truncated.shown)} of {fmtInt(truncated.total)} lookup tables.
        </div>
      ) : null}
    </div>
  );
}

// ── Analyst notes ────────────────────────────────────────────────────────────
function Notes({ notes }) {
  return (
    <div style={{ background: C.accentSoft, border: `1px solid ${C.border}`, borderRadius: 7, padding: "12px 14px" }}>
      <div style={{ ...LBL, color: C.accent, marginBottom: 8 }}>Reading this database — analyst notes</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {notes.map((n, i) => (
          <div key={i} style={{ display: "flex", gap: 8, fontSize: 12.5, lineHeight: 1.5, color: C.textBody }}>
            <span style={{ fontFamily: C.mono, color: C.accent, fontWeight: 700, flex: "none" }}>{String(i + 1).padStart(2, "0")}</span>
            <span>{n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Full table inventory, collapsed by default ───────────────────────────────
function Inventory({ tables }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderTop: `1px solid ${C.borderSubtle}`, paddingTop: 10 }}>
      <div onClick={() => setOpen((o) => !o)} style={{ cursor: "pointer", display: "flex", gap: 8, alignItems: "baseline" }}>
        <span style={{ color: C.accent, fontFamily: C.mono, fontSize: 11 }}>{open ? "▾" : "▸"}</span>
        <span style={LBL}>Every table in the database · {tables.length}</span>
      </div>
      {open ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "2px 18px", marginTop: 8 }}>
          {tables.map((t) => (
            <div key={t.name} style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 10.5, padding: "1px 0" }}>
              <span style={{ fontFamily: C.mono, color: t.role === "core" ? C.textBody : C.textDim }}>{t.name}</span>
              <span style={{ color: C.textDim, fontVariantNumeric: "tabular-nums" }}>{t.rows == null ? "?" : fmtInt(t.rows)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ── The viewer ──────────────────────────────────────────────────────────────
function AriesExplorer({ title, tldr, data }) {
  const db = data.database || {};
  const cov = data.coverage || {};
  const contextLine = [db.file, fmtBytes(db.size_bytes),
    db.schema_version ? `schema ${db.schema_version}` : null,
    db.backend ? `read via ${db.backend}` : null,
    db.projects?.length ? `project${db.projects.length === 1 ? "" : "s"}: ${db.projects.join(", ")}` : null,
  ].filter(Boolean).join(" · ");

  const tiles = [
    db.property_count != null && ["Properties", fmtInt(db.property_count), "cases in AC_PROPERTY"],
    cov.properties_with_production ? ["With production", fmtInt(cov.properties_with_production), cov.first ? `${cov.first} → ${cov.last}` : null] : null,
    data.rescat_rollup?.length && ["Reserve categories", fmtInt(data.rescat_rollup.length), data.rescat_rollup.map((r) => r.rescat).slice(0, 4).join(" ")],
    data.scenarios?.qualifiers?.length && ["Scenarios", fmtInt(data.scenarios.qualifiers.length), data.scenarios.chosen ? `decoding ${data.scenarios.chosen}` : null],
    data.lookups?.length ? ["Lookup tables", fmtInt((data.lookups_truncated || {}).total || data.lookups.length), "type curves, decks"] : null,
    db.table_count != null && ["Tables", fmtInt(db.table_count)],
  ].filter(Boolean).slice(0, 6);

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden", fontFamily: "Inter, system-ui, sans-serif" }}>
      {/* HEADER */}
      <div style={{ padding: "18px 20px", borderBottom: `1px solid ${C.border}`, background: C.panelMute }}>
        <div style={{ ...LBL, color: C.accent }}>ARIES database · explorer</div>
        <div style={{ fontSize: 23, fontWeight: 680, color: C.textPrimary, marginTop: 6, lineHeight: 1.2 }}>{title}</div>
        {contextLine ? <div style={{ fontSize: 12.5, color: C.textMuted, marginTop: 4 }}>{contextLine}</div> : null}
        {tldr ? <div style={{ fontSize: 12.5, color: C.textBody, lineHeight: 1.55, marginTop: 12, maxWidth: 640 }}>{tldr}</div> : null}
        {tiles.length ? <div style={{ marginTop: 14 }}><StatTiles tiles={tiles} /></div> : null}
      </div>

      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 18 }}>
        {data.notes?.length ? <Notes notes={data.notes} /> : null}
        {data.rescat_rollup?.length ? <RescatBar rollup={data.rescat_rollup} /> : null}
        {(data.scenarios?.qualifiers?.length || data.forecast_mix?.length) ? (
          <ScenarioAndSources scenarios={data.scenarios} forecastMix={data.forecast_mix} />
        ) : null}
        {data.integrity?.length ? <Integrity checks={data.integrity} /> : null}
        {data.properties?.length ? <PropertyGroups properties={data.properties} truncated={data.properties_truncated} /> : null}
        {data.assumptions?.length ? <Assumptions clusters={data.assumptions} truncated={data.assumptions_truncated} /> : null}
        {data.lookups?.length ? <Lookups lookups={data.lookups} truncated={data.lookups_truncated} /> : null}
        {data.inventory?.length ? <Inventory tables={data.inventory} /> : null}
      </div>

      <div style={{ padding: "9px 20px", borderTop: `1px solid ${C.borderSubtle}`, fontSize: 10.5, color: C.textDim, lineHeight: 1.5 }}>
        Every number above is read from the database or is a deterministic rollup computed by the explorer kit.
        The forecasts and assumptions shown are the database author's own — displayed here, not endorsed.
        Informational only — not a reserves report and not investment advice.
      </div>
    </div>
  );
}

// ── Fill these three in. Everything above is frozen. ────────────────────────
const DATA = null;  /* paste aries_payload.py's output verbatim */
const TITLE = "";   /* short title — deal or database name, e.g. "Bison IV ARIES database" */
const TLDR = "";    /* 1–2 sentences you write: what this database is and what to look at first */

export default function App() {
  return <AriesExplorer title={TITLE} tldr={TLDR} data={DATA} />;
}
