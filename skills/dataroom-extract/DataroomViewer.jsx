// ─────────────────────────────────────────────────────────────────────────────
// DATAROOM VIEWER — frozen, data-driven render component.
//
// Ship this VERBATIM. Do not rewrite it, do not adapt its structure per deal,
// do not embed example data into it. The ONLY thing you change per room is the
// EXTRACTION constant below — paste in that room's extraction.json and you're
// done. The component re-derives the entire view from the schema:
//
//   • The WELL is the spine. Anything carrying a `well_api` (interests, expenses,
//     revenue_observations, production_history) nests under its well.
//   • If there are no wells (a minerals/royalty room), the spine flips to TRACTS
//     and interests / division_orders nest under each tract instead.
//   • A section renders ONLY when its data is present. Null field → omitted.
//   • If a well has production_history, its decline curve leads; otherwise it's
//     a field summary. (data decides presence; these two rules decide prominence.)
//
// Trust rules are structural here, not optional: every record shows its
// provenance, extraction_notes leads as a data-quality banner, and nothing is
// derived — every number is a field from the extraction, shown as-is.
//
// Styling mirrors the Crude Code valuation widget: the graphite "signal
// instrument" chrome wrapper, a white screen, teal accent, Space Grotesk /
// Inter / Space Mono. Tokens are ported as locals because a claude.ai Artifact
// can't reach the app's index.css.
//
// Runtime: claude.ai Artifact. Deps: react + recharts + lucide-react only.
// ─────────────────────────────────────────────────────────────────────────────
import React, { useState, useMemo } from "react";
import {
  Building2, MapPin, FileText, AlertTriangle,
  ChevronRight, ChevronDown, Droplet, Coins, Receipt,
  Map as MapIcon, ScrollText, Layers, Search,
} from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

// ── Paste this room's extraction.json here. Nothing else in this file changes. ──
const EXTRACTION = {};

// ── design tokens (ported from index.css: --ac-* chrome + light content) ───────
const T = {
  // graphite faceplate chrome
  panelBg: "linear-gradient(180deg,#1c2024 0%,#15181b 60%,#101316 100%)",
  panelBorder: "#07090b",
  emblemBg: "radial-gradient(circle at 32% 26%, #2a3036, #0e1114)",
  line: "#2c3439",
  barIdle: "#39424a",
  chromeTitle: "#eef3f5",
  chromeMuted: "#7d868d",
  pillText: "#06262b",
  pillBg: "linear-gradient(180deg,#13aacb,#0a7e99)",
  pillBorder: "#0a3a42",
  screen: "#ffffff",
  screenBorder: "#06080a",
  cyan: "#0a9ec2",
  cyanDim: "#0e7490",
  cyanRgb: "10 158 194",
  // light content
  page: "#fafaf8",
  surface: "#ffffff",
  panelMute: "#f6f7f4",
  border: "#ececea",
  borderSubtle: "#f0f0ee",
  primary: "#0a0a0a",
  body: "#374151",
  muted: "#4b5563",
  dim: "#6b7280",
  accent: "#0e7490",
  up: "#059669",
  down: "#dc2626",
  amber: "#b45309",
  amberBg: "#fffbeb",
  amberBorder: "#fcd9a5",
  amberText: "#92400e",
  // fonts
  heading: "'Space Grotesk', Inter, system-ui, sans-serif",
  sans: "'Inter', system-ui, sans-serif",
  mono: "'Space Mono', ui-monospace, SFMono-Regular, monospace",
};
const glow = (a) => `rgb(${T.cyanRgb} / ${a})`;
const LBL = { fontFamily: T.mono, fontSize: 10, letterSpacing: "0.13em", textTransform: "uppercase", color: T.dim, fontWeight: 600 };

// ── formatters ───────────────────────────────────────────────────────────────
const pct = (v) => (v == null ? null : (v * 100).toFixed(3).replace(/\.?0+$/, "") + "%");
const usd = (v) => (v == null ? null : "$" + Math.round(v).toLocaleString());
function fmtVal(v) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return v.toLocaleString();
  return String(v);
}
const prettyKey = (k) =>
  k.replace(/_/g, " ").replace(/\b(usd|api|nri|wi|ri|orri|npri|tvd|md|bbl|mcf|ngl|nma|nra)\b/gi, (m) => m.toUpperCase());

const CAT_COLOR = {
  engineering: "#0e7490", title: "#6d28d9", financial: "#059669",
  legal: "#b45309", regulatory: "#a16207", marketing: "#be185d", other: "#6b7280",
};
const TYPE_COLOR = { PDP: T.up, PUD: T.amber, DUC: T.accent, SI: T.dim, PA: T.down };

// Nested, well_api-keyed children rendered as field grids (charts handled separately).
const CHILD_TYPES = [
  { key: "interests", label: "Interest", icon: Coins,
    fmt: { wi_decimal: pct, nri_decimal: pct, ri_decimal: pct, orri_decimal: pct, npri_decimal: pct } },
  { key: "expenses", label: "Economics", icon: Receipt,
    fmt: { capex_per_well_usd: usd, amount_usd: usd, opex_per_bbl_usd: usd, opex_per_well_per_month_usd: usd } },
  { key: "revenue_observations", label: "Revenue", icon: Coins,
    fmt: { price: usd, gross_revenue: usd, taxes: usd, deductions: usd, net_revenue: usd, owner_decimal: pct } },
];

// ── primitives ───────────────────────────────────────────────────────────────
function Field({ label, value, mono }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ ...LBL, fontSize: 8.5, marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 13, color: T.primary, fontFamily: mono ? T.mono : T.sans, fontVariantNumeric: "tabular-nums", wordBreak: "break-word" }}>{value}</div>
    </div>
  );
}

function Provenance({ p }) {
  if (!p) return null;
  return (
    <div style={{ marginTop: 8, padding: "7px 10px", background: T.panelMute, borderRadius: 6, fontSize: 11.5, color: T.muted, fontFamily: T.mono }}>
      <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
        <FileText size={11} style={{ color: T.dim, flexShrink: 0, position: "relative", top: 1 }} />
        <span style={{ color: T.body }}>{p.source_file}</span>
        {p.source_locator && <span style={{ color: T.dim }}>· {p.source_locator}</span>}
      </div>
      {p.notes && <div style={{ marginTop: 3, fontStyle: "italic", fontFamily: T.sans }}>{p.notes}</div>}
    </div>
  );
}

function Grid({ children }) {
  return <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12 }}>{children}</div>;
}

function recordFields(rec, fmt = {}, skip = []) {
  return Object.entries(rec)
    .filter(([k]) => k !== "provenance" && !skip.includes(k))
    .map(([k, v]) => {
      const disp = fmt[k] ? fmt[k](v) : fmtVal(v);
      return disp == null ? null : <Field key={k} label={prettyKey(k)} value={disp} mono={["api", "well_api"].includes(k)} />;
    });
}

// ── production decline chart (leads when a well has production_history) ─────────
function DeclineChart({ points }) {
  const data = useMemo(() => {
    return (points || [])
      .filter((p) => p.month)
      .slice()
      .sort((a, b) => String(a.month).localeCompare(String(b.month)))
      .map((p) => ({ month: p.month, oil: p.oil_bbl ?? null, gas: p.gas_mcf ?? null }));
  }, [points]);
  if (data.length < 2) return null;
  const hasGas = data.some((d) => d.gas != null);
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ ...LBL, fontSize: 9, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
        <Layers size={12} style={{ color: T.dim }} />
        Production · {data.length} mo
        <span style={{ color: T.up }}>● oil</span>
        {hasGas && <span style={{ color: T.down }}>● gas</span>}
      </div>
      <div style={{ height: 184, border: `1px solid ${T.border}`, borderRadius: 6, background: T.panelMute, padding: "8px 4px" }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={T.border} strokeDasharray="2 2" vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 9, fill: T.dim }} axisLine={{ stroke: T.border }} tickLine={false} minTickGap={28} />
            <YAxis tick={{ fontSize: 9, fill: T.dim }} axisLine={false} tickLine={false} width={46} />
            <Tooltip contentStyle={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 4, fontSize: 12, color: T.primary }} />
            <Line type="monotone" dataKey="oil" name="oil (bbl)" stroke={T.up} dot={false} strokeWidth={2} isAnimationActive={false} />
            {hasGas && <Line type="monotone" dataKey="gas" name="gas (mcf)" stroke={T.down} dot={false} strokeWidth={1.5} isAnimationActive={false} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── a field-grid block for nested interests / expenses / revenue ──────────────
function ChildBlock({ type, records }) {
  if (!records || records.length === 0) return null;
  const Icon = type.icon;
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ ...LBL, fontSize: 9, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
        <Icon size={12} style={{ color: T.accent }} />
        {type.label}
        {records.length > 1 && <span style={{ color: T.dim }}>· {records.length} records</span>}
      </div>
      {records.map((rec, i) => (
        <div key={i} style={{ marginBottom: i < records.length - 1 ? 10 : 0, paddingLeft: 18 }}>
          <Grid>{recordFields(rec, type.fmt, ["well_api", "tract_name", "scope"])}</Grid>
          <Provenance p={rec.provenance} />
        </div>
      ))}
    </div>
  );
}

function StatPill({ label, value }) {
  return (
    <div style={{ textAlign: "right" }}>
      <div style={{ ...LBL, fontSize: 8.5 }}>{label}</div>
      <div style={{ fontSize: 12.5, color: T.primary, fontVariantNumeric: "tabular-nums", marginTop: 1 }}>{value}</div>
    </div>
  );
}

function TypeBadge({ t }) {
  if (!t) return null;
  const c = TYPE_COLOR[t] || T.dim;
  return <span style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 700, letterSpacing: "0.05em", padding: "2px 9px", borderRadius: 5, background: c + "16", color: c, border: `1px solid ${c}33` }}>{t}</span>;
}

// ── well spine row ─────────────────────────────────────────────────────────────
function WellRow({ well, kids, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen);
  const interest = (kids.interests || [])[0];
  const expense = (kids.expenses || [])[0];
  const production = kids.production_history || [];
  return (
    <div style={{ borderTop: `1px solid ${T.borderSubtle}` }}>
      <div onClick={() => setOpen(!open)} style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 10, padding: "11px 14px", background: open ? T.panelMute : "transparent" }}>
        <span style={{ color: T.dim, flexShrink: 0 }}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
        <Droplet size={15} style={{ color: T.accent, flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: T.heading, fontSize: 14, fontWeight: 600, color: T.primary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{well.name || well.api || "Unnamed well"}</div>
          <div style={{ fontSize: 11.5, color: T.dim, fontFamily: T.mono }}>{well.api || "no API"}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
          {interest && interest.wi_decimal != null && <StatPill label="WI / NRI" value={`${pct(interest.wi_decimal)} / ${pct(interest.nri_decimal)}`} />}
          {interest && interest.wi_decimal == null && interest.ri_decimal != null && <StatPill label="RI" value={pct(interest.ri_decimal)} />}
          {expense && expense.amount_usd != null && <StatPill label="Net cost" value={usd(expense.amount_usd)} />}
          <TypeBadge t={well.well_type} />
        </div>
      </div>
      {open && (
        <div style={{ padding: "10px 14px 18px 39px", background: T.page }}>
          <Grid>{recordFields(well, {}, ["public_well_object", "name", "api"])}</Grid>
          <Provenance p={well.provenance} />
          {/* prominence rule: production leads when present */}
          {production.length >= 2 && <DeclineChart points={production} />}
          {CHILD_TYPES.map((ct) => <ChildBlock key={ct.key} type={ct} records={kids[ct.key]} />)}
        </div>
      )}
    </div>
  );
}

// ── tract spine row (minerals/royalty rooms with no wells) ─────────────────────
function TractRow({ tract, interests, divisionOrders, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ borderTop: `1px solid ${T.borderSubtle}` }}>
      <div onClick={() => setOpen(!open)} style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 10, padding: "11px 14px", background: open ? T.panelMute : "transparent" }}>
        <span style={{ color: T.dim, flexShrink: 0 }}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
        <MapIcon size={15} style={{ color: T.accent, flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: T.heading, fontSize: 14, fontWeight: 600, color: T.primary }}>{tract.name || tract.legal_description || "Tract"}</div>
          <div style={{ fontSize: 11.5, color: T.dim }}>{[tract.county, tract.state].filter(Boolean).join(", ")}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
          {tract.nma != null && <StatPill label="NMA" value={fmtVal(tract.nma)} />}
          {tract.royalty_decimal != null && <StatPill label="Royalty" value={pct(tract.royalty_decimal)} />}
        </div>
      </div>
      {open && (
        <div style={{ padding: "10px 14px 18px 39px", background: T.page }}>
          <Grid>{recordFields(tract, { royalty_decimal: pct })}</Grid>
          <Provenance p={tract.provenance} />
          <ChildBlock type={CHILD_TYPES[0]} records={interests} />
          {divisionOrders && divisionOrders.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ ...LBL, fontSize: 9, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <ScrollText size={12} style={{ color: T.accent }} /> Division orders · {divisionOrders.length}
              </div>
              {divisionOrders.map((d, i) => (
                <div key={i} style={{ marginBottom: 10, paddingLeft: 18 }}>
                  <Grid>{recordFields(d, { decimal: pct }, ["tract_name"])}</Grid>
                  <Provenance p={d.provenance} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── generic table for standalone entities (documents, leftover tracts/DOs) ─────
const STANDALONE_COLS = {
  tracts: [["name", "Name"], ["county", "County"], ["gross_acres", "Gross ac"], ["nma", "NMA"], ["royalty_decimal", "Royalty"]],
  division_orders: [["property_name", "Property"], ["well_api", "Well API"], ["decimal", "Decimal"], ["grantee", "Grantee"]],
  documents: [["path", "File"], ["category", "Category"]],
};
const STANDALONE_FMT = { tracts: { royalty_decimal: pct }, division_orders: { decimal: pct }, documents: {} };

function StandaloneTable({ entityKey, rows }) {
  const [openRow, setOpenRow] = useState(null);
  const cols = STANDALONE_COLS[entityKey];
  const fmt = STANDALONE_FMT[entityKey] || {};
  return (
    <div style={{ overflowX: "auto", border: `1px solid ${T.border}`, borderRadius: 8 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ background: T.panelMute }}>
            <th style={{ width: 28 }}></th>
            {cols.map(([k, lbl]) => (
              <th key={k} style={{ textAlign: "left", padding: "9px 10px", ...LBL, fontSize: 9 }}>{lbl}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const open = openRow === i;
            return (
              <React.Fragment key={i}>
                <tr onClick={() => setOpenRow(open ? null : i)} style={{ cursor: "pointer", borderTop: `1px solid ${T.borderSubtle}`, background: open ? T.panelMute : "transparent" }}>
                  <td style={{ padding: "7px 6px", color: T.dim }}>{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                  {cols.map(([k]) => {
                    let v = row[k];
                    let disp = fmt[k] ? fmt[k](v) : fmtVal(v);
                    if (k === "path" && typeof v === "string") disp = v.split("/").slice(-1)[0];
                    const isCat = k === "category" && v && CAT_COLOR[v];
                    return (
                      <td key={k} style={{ padding: "8px 10px", color: disp == null ? "#b8bcc4" : T.body, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums", fontFamily: ["api", "well_api"].includes(k) ? T.mono : T.sans }}>
                        {isCat ? <span style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 700, letterSpacing: "0.04em", padding: "2px 8px", borderRadius: 5, background: CAT_COLOR[v] + "16", color: CAT_COLOR[v] }}>{v}</span> : (disp ?? "—")}
                      </td>
                    );
                  })}
                </tr>
                {open && (
                  <tr style={{ background: T.page }}>
                    <td></td>
                    <td colSpan={cols.length} style={{ padding: "6px 10px 14px" }}>
                      <Grid>{recordFields(row, fmt)}</Grid>
                      <Provenance p={row.provenance} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SectionHeader({ icon: Icon, label, count }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
      <Icon size={15} style={{ color: T.accent }} />
      <h3 style={{ margin: 0, fontFamily: T.heading, fontSize: 14, fontWeight: 600, color: T.primary }}>{label}</h3>
      <span style={{ ...LBL, fontSize: 9, color: T.dim, background: T.panelMute, borderRadius: 20, padding: "2px 9px" }}>{count}</span>
    </div>
  );
}

// ── settled signal-bar level meter (static "results" reading) ──────────────────
const BAR_H = [16, 22, 14, 24, 18, 26, 15, 21];
function SignalBars() {
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 2.5, height: 26, padding: "0 11px", borderLeft: "1px solid rgba(255,255,255,.06)", borderRight: "1px solid rgba(255,255,255,.06)", flexShrink: 0 }}>
      {BAR_H.map((h, i) => (
        <span key={i} style={{ width: 3, borderRadius: 1, height: h, background: i >= 5 ? T.barIdle : T.cyan, boxShadow: i < 5 ? `0 0 6px ${glow(0.55)}` : "none" }} />
      ))}
    </div>
  );
}

// ── the "signal instrument" chrome wrapper (mirrors AgentContainer) ────────────
function Chrome({ subtitle, pill, children }) {
  return (
    <div style={{ fontFamily: T.heading, background: T.panelBg, borderRadius: 13, overflow: "hidden", border: `1px solid ${T.panelBorder}`, boxShadow: "inset 0 1px 0 rgba(120,180,200,.10), inset 0 0 0 1px rgba(255,255,255,.015), 0 24px 56px -28px rgba(0,0,0,.7)", padding: 14, position: "relative" }}>
      {/* faint cyan grid wash on the faceplate */}
      <div style={{ position: "absolute", inset: 0, backgroundImage: `linear-gradient(${glow(0.05)} 1px, transparent 1px), linear-gradient(90deg, ${glow(0.05)} 1px, transparent 1px)`, backgroundSize: "22px 22px", maskImage: "linear-gradient(180deg, rgba(0,0,0,.6), transparent 70%)", WebkitMaskImage: "linear-gradient(180deg, rgba(0,0,0,.6), transparent 70%)", pointerEvents: "none" }} />

      {/* HEADER */}
      <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 13, padding: "3px 5px 14px" }}>
        {/* emblem — concentric dial with lit core */}
        <div style={{ width: 38, height: 38, borderRadius: 9, background: T.emblemBg, border: `1px solid ${T.line}`, display: "grid", placeItems: "center", boxShadow: "inset 0 1px 1px rgba(150,210,230,.14), inset 0 0 10px rgba(0,0,0,.6)", flexShrink: 0 }}>
          <span style={{ width: 16, height: 16, borderRadius: "50%", border: `1.5px solid ${T.cyanDim}`, display: "grid", placeItems: "center" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: T.cyan, boxShadow: `0 0 8px ${T.cyan}, 0 0 14px ${glow(0.5)}` }} />
          </span>
        </div>

        {/* title + subtitle */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: T.heading, fontSize: 16.5, fontWeight: 700, letterSpacing: "-0.01em", color: T.chromeTitle, lineHeight: 1.1 }}>Dataroom Results</div>
          {subtitle && <div style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: "0.05em", color: T.chromeMuted, marginTop: 5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{subtitle.toUpperCase()}</div>}
        </div>

        <SignalBars />
        {pill && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: T.mono, fontSize: 12, fontWeight: 700, color: T.pillText, background: T.pillBg, border: `1px solid ${T.pillBorder}`, borderRadius: 5, padding: "6px 10px", boxShadow: `inset 0 1px 0 rgba(255,255,255,.4), 0 0 12px ${glow(0.28)}`, letterSpacing: "0.06em", flexShrink: 0 }}>
            {pill}
          </div>
        )}
      </div>

      {/* WHITE SCREEN — content body, light mode */}
      <div style={{ position: "relative", background: T.screen, borderRadius: 8, border: `1px solid ${T.screenBorder}`, boxShadow: `inset 0 0 0 1px ${glow(0.1)}, 0 2px 0 rgba(0,0,0,.25)`, overflow: "hidden" }}>
        <div style={{ height: 3, background: `linear-gradient(90deg, ${T.cyan}, ${T.cyanDim} 60%, transparent)` }} />
        {children}
      </div>
    </div>
  );
}

// ── top level ──────────────────────────────────────────────────────────────────
export default function DataroomViewer() {
  const data = EXTRACTION || {};
  const deal = data.deal || {};
  const [query, setQuery] = useState("");
  const wells = data.wells || [];
  const tracts = data.tracts || [];

  // spine rule: wells if present, else tracts
  const spine = wells.length > 0 ? "well" : tracts.length > 0 ? "tract" : "none";

  const childrenByApi = useMemo(() => {
    const idx = {};
    for (const ct of [...CHILD_TYPES, { key: "production_history" }]) {
      for (const rec of data[ct.key] || []) {
        if (!rec.well_api) continue;
        (idx[rec.well_api] ||= {});
        (idx[rec.well_api][ct.key] ||= []).push(rec);
      }
    }
    return idx;
  }, [data]);

  const interestsByTract = useMemo(() => {
    const idx = {};
    for (const rec of data.interests || []) {
      if (!rec.tract_name) continue;
      (idx[rec.tract_name] ||= []).push(rec);
    }
    return idx;
  }, [data]);
  const dosByTract = useMemo(() => {
    const idx = {};
    for (const rec of data.division_orders || []) {
      if (!rec.property_name) continue;
      (idx[rec.property_name] ||= []).push(rec);
    }
    return idx;
  }, [data]);

  const q = query.trim().toLowerCase();
  const matches = (obj, extra) => !q || (JSON.stringify(obj) + JSON.stringify(extra || {})).toLowerCase().includes(q);
  const shownWells = wells.filter((w) => matches(w, childrenByApi[w.api]));
  const shownTracts = tracts.filter((t) => matches(t, interestsByTract[t.name]));

  const headerStats = [
    deal.category && ["Interest", deal.category],
    deal.well_count != null && ["Wells", deal.well_count],
    deal.gross_acres != null && ["Gross acres", deal.gross_acres.toLocaleString()],
    deal.net_acres != null && ["Net acres", deal.net_acres.toLocaleString()],
    deal.pv10_mid_mm != null && ["Seller PV10", "$" + deal.pv10_mid_mm + "MM"],
    deal.basin && ["Basin", deal.basin],
  ].filter(Boolean);

  // standalone sections = entities that aren't the spine
  const standalone = [];
  if (spine !== "tract" && tracts.length > 0) standalone.push(["tracts", "Tracts", MapIcon, tracts]);
  if (spine !== "tract" && (data.division_orders || []).length > 0) standalone.push(["division_orders", "Division orders", ScrollText, data.division_orders]);
  if ((data.documents || []).length > 0) standalone.push(["documents", "Documents", FileText, data.documents]);

  const subtitle = [deal.seller, [deal.county, deal.state].filter(Boolean).join(", "), deal.formation].filter(Boolean).join("  ·  ") || deal.title || "Extraction";
  const pill = spine === "well"
    ? `${deal.category ? deal.category + " · " : ""}${wells.length} ${wells.length === 1 ? "WELL" : "WELLS"}`
    : spine === "tract"
      ? `${tracts.length} ${tracts.length === 1 ? "TRACT" : "TRACTS"}`
      : "EXTRACTION";

  return (
    <div style={{ fontFamily: T.sans, color: T.body }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');`}</style>

      <Chrome subtitle={subtitle} pill={pill}>
        <div style={{ padding: "20px 22px 26px" }}>
          {/* deal header band */}
          <div style={{ borderBottom: `1px solid ${T.border}`, paddingBottom: 18, marginBottom: 20 }}>
            <div style={{ ...LBL, fontSize: 9, color: T.accent, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
              Dataroom extraction
              {deal.process_type && <span style={{ color: T.dim }}>· {deal.process_type}</span>}
            </div>
            <h1 style={{ margin: "0 0 8px", fontFamily: T.heading, fontSize: 22, fontWeight: 700, lineHeight: 1.2, color: T.primary }}>{deal.title || "Untitled extraction"}</h1>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", fontSize: 13, color: T.muted, marginBottom: headerStats.length ? 16 : 0 }}>
              {deal.seller && <span><Building2 size={12} style={{ verticalAlign: -1, marginRight: 4 }} />{deal.seller}</span>}
              {deal.operator && <span>Operated by {deal.operator}</span>}
              {(deal.county || deal.state) && <span><MapPin size={12} style={{ verticalAlign: -1, marginRight: 4 }} />{[deal.county, deal.state].filter(Boolean).join(", ")}</span>}
              {deal.formation && <span>{deal.formation}</span>}
              {deal.broker && <span>Broker: {deal.broker}</span>}
            </div>
            {headerStats.length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 1, background: T.border, border: `1px solid ${T.border}`, borderRadius: 7, overflow: "hidden", marginBottom: deal.summary ? 16 : 0 }}>
                {headerStats.map(([lbl, val]) => (
                  <div key={lbl} style={{ background: T.surface, padding: "10px 12px" }}>
                    <div style={{ ...LBL, fontSize: 8.5 }}>{lbl}</div>
                    <div style={{ fontFamily: T.heading, fontSize: 18, fontWeight: 600, marginTop: 3, color: T.primary, fontVariantNumeric: "tabular-nums" }}>{val}</div>
                  </div>
                ))}
              </div>
            )}
            {deal.summary && <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: T.body }}>{deal.summary}</p>}
          </div>

          {/* data-quality banner */}
          {data.extraction_notes && (
            <div style={{ display: "flex", gap: 10, padding: "12px 14px", background: T.amberBg, border: `1px solid ${T.amberBorder}`, borderRadius: 8, marginBottom: 22 }}>
              <AlertTriangle size={16} style={{ color: T.amber, flexShrink: 0, marginTop: 1 }} />
              <div>
                <div style={{ ...LBL, fontSize: 9, color: T.amber, marginBottom: 5 }}>Extraction notes &amp; data quality</div>
                <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.6, color: T.amberText }}>{data.extraction_notes}</p>
              </div>
            </div>
          )}

          {spine !== "none" && (
            <>
              <div style={{ position: "relative", marginBottom: 18 }}>
                <Search size={15} style={{ position: "absolute", left: 11, top: 10, color: T.dim }} />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by name, API, or any nested value…"
                       style={{ width: "100%", boxSizing: "border-box", padding: "8px 12px 8px 34px", fontFamily: T.sans, fontSize: 13, border: `1px solid ${T.border}`, borderRadius: 8, outline: "none", background: T.surface, color: T.primary }} />
              </div>

              <div style={{ marginBottom: 26 }}>
                {spine === "well" ? (
                  <>
                    <SectionHeader icon={Droplet} label="Wells" count={q ? `${shownWells.length}/${wells.length}` : wells.length} />
                    <div style={{ border: `1px solid ${T.border}`, borderRadius: 8, overflow: "hidden" }}>
                      {shownWells.length === 0 && <div style={{ padding: 16, fontSize: 13, color: T.dim }}>No wells match the filter.</div>}
                      {shownWells.map((w, i) => <WellRow key={w.api ? w.api + i : i} well={w} kids={childrenByApi[w.api] || {}} defaultOpen={wells.length === 1} />)}
                    </div>
                  </>
                ) : (
                  <>
                    <SectionHeader icon={MapIcon} label="Tracts" count={q ? `${shownTracts.length}/${tracts.length}` : tracts.length} />
                    <div style={{ border: `1px solid ${T.border}`, borderRadius: 8, overflow: "hidden" }}>
                      {shownTracts.length === 0 && <div style={{ padding: 16, fontSize: 13, color: T.dim }}>No tracts match the filter.</div>}
                      {shownTracts.map((t, i) => <TractRow key={i} tract={t} interests={interestsByTract[t.name]} divisionOrders={dosByTract[t.name]} defaultOpen={tracts.length === 1} />)}
                    </div>
                  </>
                )}
              </div>
            </>
          )}

          {standalone.map(([key, label, icon, rows]) => (
            <div key={key} style={{ marginBottom: 24 }}>
              <SectionHeader icon={icon} label={label} count={rows.length} />
              <StandaloneTable entityKey={key} rows={rows} />
            </div>
          ))}
        </div>
      </Chrome>
    </div>
  );
}
