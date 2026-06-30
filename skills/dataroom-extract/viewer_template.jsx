// ─────────────────────────────────────────────────────────────────────────────
// DATAROOM VIEWER — TEMPLATE / SCAFFOLD (not a finished app)
//
// This lays out the *menu* of sections a dataroom viewer can have. Build the real
// artifact from this: keep the sections the extraction supports, delete the ones
// it doesn't, and flesh out the rendering. Do NOT ship this skeleton as-is, and
// do NOT clone it field-for-field — every dataroom emphasizes different things.
//
// The model: the WELL is the spine. Anything carrying a `well_api`
// (interests, expenses, revenue_observations, production_history) nests under its
// well. Entities that don't join a well (tracts, division_orders, documents) get
// their own standalone section. For a minerals/royalty deal (category MI/RI/ORRI/
// NPRI) where `wells` is empty, flip the spine to TRACTS and nest interests/
// division_orders under each tract instead.
//
// TRUST RULES (the display-side analog of the extraction's "never fabricate"):
//   • Derive nothing. Every number on screen is a field from the extraction,
//     shown as-is. No invented totals, no PV, no per-BOE math in this component.
//   • Every record shows its provenance. Lead with extraction_notes.
//   • Render only what's present — null field → omit it; empty list → no section.
//
// Self-contained: react + recharts + lucide-react only. No network calls.
// ─────────────────────────────────────────────────────────────────────────────
import React, { useState, useMemo } from "react";
// import { Building2, MapPin, FileText, Droplet, Coins, Receipt, Layers, AlertTriangle } from "lucide-react";
// import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

// Paste extraction.json here (or wire it in as a prop) so the artifact runs standalone.
const EXTRACTION = /* extraction.json */ {};

// ── helpers ──────────────────────────────────────────────────────────────────
const pct = (v) => (v == null ? null : (v * 100).toFixed(3).replace(/\.?0+$/, "") + "%");
const usd = (v) => (v == null ? null : "$" + Math.round(v).toLocaleString());
const present = (v) => v !== null && v !== undefined && v !== "";

// Provenance is MANDATORY on every rendered record — it's the trust anchor.
function Provenance({ p }) {
  if (!p) return null;
  return (
    <div className="provenance">
      {p.source_file}{p.source_locator ? ` · ${p.source_locator}` : ""}
      {p.notes ? <em> — {p.notes}</em> : null}
    </div>
  );
}

export default function DataroomViewer() {
  const data = EXTRACTION;
  const deal = data.deal || {};

  // Index every well_api-keyed child under its well so the spine can nest them.
  const childrenByApi = useMemo(() => {
    const idx = {};
    for (const key of ["interests", "expenses", "revenue_observations", "production_history"]) {
      for (const rec of data[key] || []) {
        if (!rec.well_api) continue;
        (idx[rec.well_api] ||= {});
        (idx[rec.well_api][key] ||= []).push(rec);
      }
    }
    return idx;
  }, [data]);

  return (
    <div className="dataroom-viewer">

      {/* ── SECTION 1 · DEAL HEADER (from `deal`) ──────────────────────────────
          Lead metadata. Title, seller / operator / broker, county·state·basin·
          formation, then the headline stat tiles (category, well_count,
          gross_acres, pv10_mid_mm, current_net_boed — whichever are present),
          then `summary`. Omit any null field. */}
      <header>
        <h1>{deal.title || "Dataroom extraction"}</h1>
        {/* sub-line: seller, operator, location, formation, broker — only what's present */}
        {/* stat tiles: build from the deal fields that are non-null */}
        {present(deal.summary) && <p>{deal.summary}</p>}
      </header>

      {/* ── SECTION 2 · DATA-QUALITY BANNER (from `extraction_notes`) ──────────
          ALWAYS render when present, near the top. This is where caveats,
          excluded offsets, un-OCR'd files, and inferred values are disclosed. */}
      {present(data.extraction_notes) && (
        <aside className="data-quality">{data.extraction_notes}</aside>
      )}

      {/* ── SECTION 3 · THE SPINE · WELLS (from `wells`) ───────────────────────
          One expandable row per well. Header line: name + API, a WI/NRI readout
          from its interest, a status pill (well_type: PDP/PUD/DUC/SI/PA).
          Expanded body shows the well's own fields, its Provenance, then the
          nested child blocks below.
          (Minerals deal with no wells? Delete this section and make TRACTS the
          spine instead — nest interests/division_orders under each tract.) */}
      <section>
        {(data.wells || []).map((well, i) => {
          const kids = childrenByApi[well.api] || {};
          return (
            <WellRow key={well.api || i} well={well} kids={kids} />
          );
        })}
      </section>

      {/* ── SECTION 4 · STANDALONE ENTITIES ────────────────────────────────────
          Entities that don't join a well — render each as its own table, and
          only when the list is non-empty.
            • tracts           → matters for mineral / royalty deals
            • division_orders  → decimal interest by property
            • documents        → the audit-trail file inventory (category pills)
          */}
      {(data.tracts || []).length > 0 && <StandaloneTable rows={data.tracts} title="Tracts" />}
      {(data.division_orders || []).length > 0 && <StandaloneTable rows={data.division_orders} title="Division orders" />}
      {(data.documents || []).length > 0 && <StandaloneTable rows={data.documents} title="Documents" />}
    </div>
  );
}

// ── A well and everything hanging off it ──────────────────────────────────────
function WellRow({ well, kids }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      {/* collapsed header: well.name / well.api · WI·NRI from kids.interests[0] · well_type pill */}
      <div onClick={() => setOpen(!open)}>{well.name || well.api}</div>
      {open && (
        <div>
          {/* well's own fields (formation, trajectory, lateral_length_ft, …) — present() only */}
          <Provenance p={well.provenance} />

          {/* NESTED CHILDREN — render each block only if kids[...] is non-empty:

              • interests            → WI / NRI / RI / NPRI / ORRI / MI decimals (pct)
              • expenses             → opex (per-bbl / per-well-month) + capex_per_well_usd (usd)
              • revenue_observations → realized price, gross, taxes, deductions, net (usd)
                   ↳ if there are several months, a price/differential CHART beats a table
              • production_history   → monthly oil / gas / water / ngl
                   ↳ when present, a DECLINE CHART (recharts LineChart) is the right call,
                     not a field grid
          */}
        </div>
      )}
    </div>
  );
}

// ── Generic table for standalone entities (tracts / division_orders / documents) ──
function StandaloneTable({ rows, title }) {
  // Pick the columns that matter for this entity; expand a row to show all fields
  // + Provenance. Documents: show the filename and a category pill.
  return (
    <section>
      <h3>{title} · {rows.length}</h3>
      {/* table rows … each with its Provenance on expand */}
    </section>
  );
}
