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
// Runtime: claude.ai Artifact. Deps: react + recharts + lucide-react only.
// ─────────────────────────────────────────────────────────────────────────────
import React, { useState, useMemo } from "react";
import {
  Building2, MapPin, FileText, Database, AlertTriangle,
  ChevronRight, ChevronDown, Droplet, Coins, Receipt,
  Map as MapIcon, ScrollText, Layers, Search,
} from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

// ── Paste this room's extraction.json here. Nothing else in this file changes. ──
const EXTRACTION = {};

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
  engineering: "#185FA5", title: "#534AB7", financial: "#0F6E56",
  legal: "#993C1D", regulatory: "#854F0B", marketing: "#993556", other: "#5F5E5A",
};
const TYPE_COLOR = { PDP: "#0F6E56", PUD: "#854F0B", DUC: "#185FA5", SI: "#5F5E5A", PA: "#993C1D" };

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
      <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".04em", color: "#888780", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, color: "#2C2C2A", fontFamily: mono ? "ui-monospace, monospace" : "inherit", wordBreak: "break-word" }}>{value}</div>
    </div>
  );
}

function Provenance({ p }) {
  if (!p) return null;
  return (
    <div style={{ marginTop: 8, padding: "7px 10px", background: "#F1EFE8", borderRadius: 6, fontSize: 11.5, color: "#5F5E5A", fontFamily: "ui-monospace, monospace" }}>
      <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
        <FileText size={11} style={{ color: "#888780", flexShrink: 0, position: "relative", top: 1 }} />
        <span style={{ color: "#2C2C2A" }}>{p.source_file}</span>
        {p.source_locator && <span style={{ color: "#888780" }}>· {p.source_locator}</span>}
      </div>
      {p.notes && <div style={{ marginTop: 3, fontStyle: "italic", fontFamily: "inherit" }}>{p.notes}</div>}
    </div>
  );
}

function Grid({ children }) {
  return <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>{children}</div>;
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
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <Layers size={13} style={{ color: "#5F5E5A" }} />
        <span style={{ fontSize: 12, fontWeight: 500, color: "#5F5E5A", textTransform: "uppercase", letterSpacing: ".04em" }}>Production · {data.length} mo</span>
      </div>
      <div style={{ height: 180 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#E8E6DE" strokeDasharray="2 2" vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#888780" }} minTickGap={28} />
            <YAxis tick={{ fontSize: 10, fill: "#888780" }} width={44} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 6, border: "0.5px solid #D3D1C7" }} />
            <Line type="monotone" dataKey="oil" name="Oil (bbl)" stroke="#0F6E56" dot={false} strokeWidth={1.5} />
            {hasGas && <Line type="monotone" dataKey="gas" name="Gas (mcf)" stroke="#185FA5" dot={false} strokeWidth={1.5} />}
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
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <Icon size={13} style={{ color: "#5F5E5A" }} />
        <span style={{ fontSize: 12, fontWeight: 500, color: "#5F5E5A", textTransform: "uppercase", letterSpacing: ".04em" }}>{type.label}</span>
        {records.length > 1 && <span style={{ fontSize: 11, color: "#888780" }}>· {records.length} records</span>}
      </div>
      {records.map((rec, i) => (
        <div key={i} style={{ marginBottom: i < records.length - 1 ? 10 : 0, paddingLeft: 19 }}>
          <Grid>{recordFields(rec, type.fmt, ["well_api", "tract_name", "scope"])}</Grid>
          <Provenance p={rec.provenance} />
        </div>
      ))}
    </div>
  );
}

// ── well spine row ─────────────────────────────────────────────────────────────
function WellRow({ well, kids, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen);
  const t = well.well_type;
  const interest = (kids.interests || [])[0];
  const expense = (kids.expenses || [])[0];
  const production = kids.production_history || [];
  return (
    <div style={{ borderTop: "0.5px solid #E8E6DE" }}>
      <div onClick={() => setOpen(!open)} style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 10, padding: "11px 12px", background: open ? "#F8F7F2" : "transparent" }}>
        <span style={{ color: "#888780", flexShrink: 0 }}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
        <Droplet size={15} style={{ color: "#185FA5", flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: "#2C2C2A", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{well.name || well.api || "Unnamed well"}</div>
          <div style={{ fontSize: 12, color: "#888780", fontFamily: "ui-monospace, monospace" }}>{well.api || "no API"}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexShrink: 0 }}>
          {interest && interest.wi_decimal != null && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 10.5, color: "#888780", textTransform: "uppercase", letterSpacing: ".04em" }}>WI / NRI</div>
              <div style={{ fontSize: 12.5, color: "#2C2C2A" }}>{pct(interest.wi_decimal)} / {pct(interest.nri_decimal)}</div>
            </div>
          )}
          {interest && interest.wi_decimal == null && interest.ri_decimal != null && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 10.5, color: "#888780", textTransform: "uppercase", letterSpacing: ".04em" }}>RI</div>
              <div style={{ fontSize: 12.5, color: "#2C2C2A" }}>{pct(interest.ri_decimal)}</div>
            </div>
          )}
          {expense && expense.amount_usd != null && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 10.5, color: "#888780", textTransform: "uppercase", letterSpacing: ".04em" }}>Net cost</div>
              <div style={{ fontSize: 12.5, color: "#2C2C2A" }}>{usd(expense.amount_usd)}</div>
            </div>
          )}
          {t && <span style={{ fontSize: 11, fontWeight: 500, padding: "2px 9px", borderRadius: 20, background: (TYPE_COLOR[t] || "#5F5E5A") + "1A", color: TYPE_COLOR[t] || "#5F5E5A" }}>{t}</span>}
        </div>
      </div>
      {open && (
        <div style={{ padding: "4px 12px 18px 37px", background: "#FCFCFB" }}>
          <div style={{ paddingTop: 8 }}>
            <Grid>{recordFields(well, {}, ["public_well_object", "name", "api"])}</Grid>
          </div>
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
    <div style={{ borderTop: "0.5px solid #E8E6DE" }}>
      <div onClick={() => setOpen(!open)} style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 10, padding: "11px 12px", background: open ? "#F8F7F2" : "transparent" }}>
        <span style={{ color: "#888780", flexShrink: 0 }}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
        <MapIcon size={15} style={{ color: "#534AB7", flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: "#2C2C2A" }}>{tract.name || tract.legal_description || "Tract"}</div>
          <div style={{ fontSize: 12, color: "#888780" }}>{[tract.county, tract.state].filter(Boolean).join(", ")}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexShrink: 0 }}>
          {tract.nma != null && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 10.5, color: "#888780", textTransform: "uppercase", letterSpacing: ".04em" }}>NMA</div>
              <div style={{ fontSize: 12.5, color: "#2C2C2A" }}>{fmtVal(tract.nma)}</div>
            </div>
          )}
          {tract.royalty_decimal != null && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 10.5, color: "#888780", textTransform: "uppercase", letterSpacing: ".04em" }}>Royalty</div>
              <div style={{ fontSize: 12.5, color: "#2C2C2A" }}>{pct(tract.royalty_decimal)}</div>
            </div>
          )}
        </div>
      </div>
      {open && (
        <div style={{ padding: "4px 12px 18px 37px", background: "#FCFCFB" }}>
          <div style={{ paddingTop: 8 }}><Grid>{recordFields(tract, { royalty_decimal: pct })}</Grid></div>
          <Provenance p={tract.provenance} />
          <ChildBlock type={CHILD_TYPES[0]} records={interests} />
          {divisionOrders && divisionOrders.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                <ScrollText size={13} style={{ color: "#5F5E5A" }} />
                <span style={{ fontSize: 12, fontWeight: 500, color: "#5F5E5A", textTransform: "uppercase", letterSpacing: ".04em" }}>Division orders · {divisionOrders.length}</span>
              </div>
              {divisionOrders.map((d, i) => (
                <div key={i} style={{ marginBottom: 10, paddingLeft: 19 }}>
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
    <div style={{ overflowX: "auto", border: "0.5px solid #D3D1C7", borderRadius: 8 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ background: "#F8F7F2" }}>
            <th style={{ width: 28 }}></th>
            {cols.map(([k, lbl]) => (
              <th key={k} style={{ textAlign: "left", padding: "8px 10px", fontWeight: 500, color: "#5F5E5A", fontSize: 11, textTransform: "uppercase", letterSpacing: ".03em", whiteSpace: "nowrap" }}>{lbl}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const open = openRow === i;
            return (
              <React.Fragment key={i}>
                <tr onClick={() => setOpenRow(open ? null : i)} style={{ cursor: "pointer", borderTop: "0.5px solid #E8E6DE", background: open ? "#F8F7F2" : "transparent" }}>
                  <td style={{ padding: "7px 6px", color: "#888780" }}>{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                  {cols.map(([k]) => {
                    let v = row[k];
                    let disp = fmt[k] ? fmt[k](v) : fmtVal(v);
                    if (k === "path" && typeof v === "string") disp = v.split("/").slice(-1)[0];
                    const isCat = k === "category" && v && CAT_COLOR[v];
                    return (
                      <td key={k} style={{ padding: "7px 10px", color: disp == null ? "#B4B2A9" : "#2C2C2A", whiteSpace: "nowrap", fontFamily: ["api", "well_api"].includes(k) ? "ui-monospace, monospace" : "inherit" }}>
                        {isCat ? <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 20, background: CAT_COLOR[v] + "1A", color: CAT_COLOR[v], fontWeight: 500 }}>{v}</span> : (disp ?? "—")}
                      </td>
                    );
                  })}
                </tr>
                {open && (
                  <tr style={{ background: "#FCFCFB" }}>
                    <td></td>
                    <td colSpan={cols.length} style={{ padding: "4px 10px 14px" }}>
                      <div style={{ paddingTop: 4 }}><Grid>{recordFields(row, fmt)}</Grid></div>
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
      <Icon size={16} style={{ color: "#2C2C2A" }} />
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 500, color: "#2C2C2A" }}>{label}</h3>
      <span style={{ fontSize: 12, color: "#888780", background: "#F1EFE8", borderRadius: 20, padding: "1px 9px", fontWeight: 500 }}>{count}</span>
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
      const key = rec.property_name;
      if (!key) continue;
      (idx[key] ||= []).push(rec);
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

  return (
    <div style={{ fontFamily: "ui-sans-serif, system-ui, sans-serif", color: "#2C2C2A", maxWidth: 960, margin: "0 auto", padding: "4px 0 32px" }}>
      <div style={{ borderBottom: "0.5px solid #D3D1C7", paddingBottom: 18, marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#888780", marginBottom: 6 }}>
          <Database size={13} /> Dataroom extraction
          {deal.process_type && <span style={{ background: "#F1EFE8", padding: "1px 8px", borderRadius: 20 }}>{deal.process_type}</span>}
        </div>
        <h1 style={{ margin: "0 0 6px", fontSize: 22, fontWeight: 500, lineHeight: 1.25 }}>{deal.title || "Untitled extraction"}</h1>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", fontSize: 13, color: "#5F5E5A", marginBottom: 14 }}>
          {deal.seller && <span><Building2 size={12} style={{ verticalAlign: -1, marginRight: 4 }} />{deal.seller}</span>}
          {deal.operator && <span>Operated by {deal.operator}</span>}
          {(deal.county || deal.state) && <span><MapPin size={12} style={{ verticalAlign: -1, marginRight: 4 }} />{[deal.county, deal.state].filter(Boolean).join(", ")}</span>}
          {deal.formation && <span>{deal.formation}</span>}
          {deal.broker && <span>Broker: {deal.broker}</span>}
        </div>
        {headerStats.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10, marginBottom: deal.summary ? 14 : 0 }}>
            {headerStats.map(([lbl, val]) => (
              <div key={lbl} style={{ background: "#F8F7F2", borderRadius: 8, padding: "10px 12px" }}>
                <div style={{ fontSize: 11, color: "#888780", textTransform: "uppercase", letterSpacing: ".04em" }}>{lbl}</div>
                <div style={{ fontSize: 18, fontWeight: 500, marginTop: 2 }}>{val}</div>
              </div>
            ))}
          </div>
        )}
        {deal.summary && <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.6, color: "#5F5E5A" }}>{deal.summary}</p>}
      </div>

      {data.extraction_notes && (
        <div style={{ display: "flex", gap: 10, padding: "12px 14px", background: "#FAEEDA", border: "0.5px solid #FAC775", borderRadius: 8, marginBottom: 22 }}>
          <AlertTriangle size={16} style={{ color: "#854F0B", flexShrink: 0, marginTop: 1 }} />
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 500, color: "#633806", marginBottom: 4 }}>Extraction notes &amp; data quality</div>
            <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.6, color: "#633806" }}>{data.extraction_notes}</p>
          </div>
        </div>
      )}

      {spine !== "none" && (
        <>
          <div style={{ position: "relative", marginBottom: 18 }}>
            <Search size={15} style={{ position: "absolute", left: 11, top: 10, color: "#888780" }} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by name, API, or any nested value…"
                   style={{ width: "100%", boxSizing: "border-box", padding: "8px 12px 8px 34px", fontSize: 13, border: "0.5px solid #D3D1C7", borderRadius: 8, outline: "none", background: "#FFF", color: "#2C2C2A" }} />
          </div>

          <div style={{ marginBottom: 28 }}>
            {spine === "well" ? (
              <>
                <SectionHeader icon={Droplet} label="Wells" count={q ? `${shownWells.length}/${wells.length}` : wells.length} />
                <div style={{ border: "0.5px solid #D3D1C7", borderRadius: 8, overflow: "hidden" }}>
                  {shownWells.length === 0 && <div style={{ padding: 16, fontSize: 13, color: "#B4B2A9" }}>No wells match the filter.</div>}
                  {shownWells.map((w, i) => <WellRow key={w.api ? w.api + i : i} well={w} kids={childrenByApi[w.api] || {}} defaultOpen={wells.length === 1} />)}
                </div>
              </>
            ) : (
              <>
                <SectionHeader icon={MapIcon} label="Tracts" count={q ? `${shownTracts.length}/${tracts.length}` : tracts.length} />
                <div style={{ border: "0.5px solid #D3D1C7", borderRadius: 8, overflow: "hidden" }}>
                  {shownTracts.length === 0 && <div style={{ padding: 16, fontSize: 13, color: "#B4B2A9" }}>No tracts match the filter.</div>}
                  {shownTracts.map((t, i) => (
                    <TractRow key={i} tract={t} interests={interestsByTract[t.name]} divisionOrders={dosByTract[t.name]} defaultOpen={tracts.length === 1} />
                  ))}
                </div>
              </>
            )}
          </div>
        </>
      )}

      {standalone.map(([key, label, icon, rows]) => (
        <div key={key} style={{ marginBottom: 26 }}>
          <SectionHeader icon={icon} label={label} count={rows.length} />
          <StandaloneTable entityKey={key} rows={rows} />
        </div>
      ))}
    </div>
  );
}
