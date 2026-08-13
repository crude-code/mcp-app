// Crude Code dataroom viewer — frozen artifact template.
// Paste viewer_payload.py's output into DATA at the bottom; write TITLE and
// TLDR. Do not restyle or restructure. Dependencies: react only.
//
// The viewer is the room's cover page: what's in the package, what the
// extraction flagged, and where every number sits — a triage surface, not a
// record browser (the persisted extraction is the durable record). It is
// data-driven: every module renders only when the payload carries its data —
// a minerals room shows tracts instead of the well manifest, a room with no
// revenue drops the LTM column and share bars, no flags → no flags block.
// Every derived number (LTM rollups, shares, interest sums) is computed
// deterministically by viewer_payload.py — nothing here or in the fill step
// does arithmetic on the room's economics.
import { useState } from "react";

// ── Palette — matches the deal-sheet template so the two read as siblings ───
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
  barTrack: "#e8e9e6",
  mono: "ui-monospace, SFMono-Regular, Menlo, monospace",
};
const LBL = {
  fontFamily: C.mono, fontSize: 10, letterSpacing: "0.13em",
  textTransform: "uppercase", color: C.textDim, fontWeight: 600,
};
const TILE_K = { ...LBL, fontSize: 8.5 };
const TH = { ...LBL, fontSize: 8.5, textAlign: "right", padding: "4px 8px", whiteSpace: "nowrap" };

const fmtUSD = (v) => `$${Math.round(v).toLocaleString("en-US")}`;
const fmtCompact = (v) => {
  const a = Math.abs(v), sign = v < 0 ? "-" : "";
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sign}$${Math.round(a / 1e3)}K`;
  return `${sign}$${Math.round(a)}`;
};
const fmtInt = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-US"));
const fmtPct = (v) => (v == null ? "—" : v.toFixed(3).replace(/\.?0+$/, "") + "%");
const fmtMonth = (d) => (d ? String(d).slice(0, 7) : "—");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtDay = (d) => {
  const [y, m, day] = String(d).split("-").map(Number);
  return `${MONTHS[m - 1] ?? ""} ${day ?? ""}, ${y}`;
};
const daysUntil = (d) => Math.ceil((new Date(`${d}T00:00:00`) - Date.now()) / 86400000);

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

function SectionShell({ label, right, open, onToggle, children }) {
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflow: "hidden" }}>
      <div onClick={onToggle} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 14px", cursor: "pointer", background: open ? C.panelMute : "transparent" }}>
        <span style={{ color: C.accent, fontFamily: C.mono, fontSize: 11, width: 10 }}>{open ? "▾" : "▸"}</span>
        <span style={{ minWidth: 0, flex: 1, display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>{label}</span>
        {right ? <span style={{ fontSize: 12, color: C.textMuted, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{right}</span> : null}
      </div>
      {open ? <div style={{ borderTop: `1px solid ${C.borderSubtle}` }}>{children}</div> : null}
    </div>
  );
}

// ── Flags — the read-before-bidding list ────────────────────────────────────
function Flags({ flags }) {
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 6 }}>Flags · {flags.length}</div>
      <div style={{ display: "grid", gridTemplateColumns: flags.length > 1 ? "1fr 1fr" : "1fr", gap: "2px 28px" }}>
        {flags.map((f, i) => (
          <div key={i} style={{ display: "flex", gap: 8, fontSize: 12.5, lineHeight: 1.45, padding: "4px 0", color: C.textBody }}>
            <span style={{ fontFamily: C.mono, color: C.flag, fontWeight: 700, flex: "none" }}>{String(i + 1).padStart(2, "0")}</span>
            <span>{f}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Well manifest — one collapsible group per status, columns data-driven ───
function ManifestGroup({ group, packageLtm, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen);
  const rows = group.wells;
  const has = (k) => rows.some((r) => r[k] != null);
  const cols = [
    has("operator") && { k: "operator", h: "Operator", align: "left", f: (r) => r.operator },
    has("formation") && { k: "formation", h: "Formation", align: "left", f: (r) => r.formation },
    has("wi_pct") && { k: "wi_pct", h: "WI %", f: (r) => fmtPct(r.wi_pct) },
    has("nri_pct") && { k: "nri_pct", h: "NRI %", f: (r) => fmtPct(r.nri_pct) },
    has("ri_pct") && { k: "ri_pct", h: "RI %", f: (r) => fmtPct(r.ri_pct) },
    has("lateral_ft") && { k: "lateral_ft", h: "Lat ft", f: (r) => fmtInt(r.lateral_ft) },
    has("first_prod") && { k: "first_prod", h: "First prod", f: (r) => fmtMonth(r.first_prod) },
    has("ltm_net_revenue") && { k: "ltm", h: "LTM net rev", f: (r) => (r.ltm_net_revenue == null ? "—" : fmtUSD(r.ltm_net_revenue)) },
  ].filter(Boolean);
  const hasShare = has("revenue_share_pct");
  const span = 1 + cols.length + (hasShare ? 1 : 0);

  return (
    <SectionShell
      open={open}
      onToggle={() => setOpen((o) => !o)}
      label={
        <>
          <span style={{ fontSize: 13.5, fontWeight: 650, color: C.textPrimary }}>
            {group.label} <span style={{ fontWeight: 400, color: C.textDim }}>({group.status})</span>
          </span>
          <span style={{ fontSize: 12, color: C.textDim }}>{group.well_count} well{group.well_count === 1 ? "" : "s"}</span>
        </>
      }
      right={group.ltm_net_revenue != null ? `${fmtUSD(group.ltm_net_revenue)} LTM net rev` : null}
    >
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ ...TH, textAlign: "left" }}>Well</th>
              {cols.map((c) => <th key={c.k} style={{ ...TH, textAlign: c.align || "right" }}>{c.h}</th>)}
              {hasShare ? <th style={{ ...TH, width: 74 }} /> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <FragmentRow key={r.api || r.name || i} r={r} cols={cols} hasShare={hasShare} span={span} />
            ))}
          </tbody>
        </table>
      </div>
    </SectionShell>
  );
}

function FragmentRow({ r, cols, hasShare, span }) {
  return (
    <>
      <tr style={{ borderTop: `1px solid ${C.borderSubtle}` }}>
        <td style={{ padding: "5px 8px", fontWeight: 550, color: C.textPrimary, whiteSpace: "nowrap" }}>
          {r.name || r.api || "—"}
          {r.note ? <span style={{ color: C.flag, marginLeft: 5 }} title={r.note}>⚑</span> : null}
        </td>
        {cols.map((c) => (
          <td key={c.k} style={{ padding: "5px 8px", textAlign: c.align || "right", fontVariantNumeric: "tabular-nums", color: c.align === "left" ? C.textDim : C.textBody, whiteSpace: "nowrap" }}>
            {c.f(r) ?? "—"}
          </td>
        ))}
        {hasShare ? (
          <td style={{ padding: "5px 8px" }}>
            <div style={{ height: 5, background: C.barTrack, borderRadius: 2 }}>
              <div style={{ height: "100%", background: C.accent, borderRadius: 2, width: `${Math.max(r.revenue_share_pct ?? 0, r.revenue_share_pct != null ? 0.5 : 0)}%` }} />
            </div>
          </td>
        ) : null}
      </tr>
      {r.note ? (
        <tr>
          <td colSpan={span} style={{ padding: "0 8px 6px 22px", fontSize: 11, color: C.flag, lineHeight: 1.4 }}>{r.note}</td>
        </tr>
      ) : null}
    </>
  );
}

// ── Tracts — the spine for minerals / royalty rooms ─────────────────────────
function TractsTable({ tracts }) {
  const has = (k) => tracts.some((t) => t[k] != null);
  const cols = [
    has("county") && { k: "county", h: "County", align: "left", f: (t) => [t.county, t.state].filter(Boolean).join(", ") },
    has("gross_acres") && { k: "gross_acres", h: "Gross ac", f: (t) => fmtInt(t.gross_acres) },
    has("nma") && { k: "nma", h: "NMA", f: (t) => (t.nma == null ? "—" : t.nma.toLocaleString("en-US")) },
    has("nra") && { k: "nra", h: "NRA", f: (t) => (t.nra == null ? "—" : t.nra.toLocaleString("en-US")) },
    has("royalty_pct") && { k: "royalty_pct", h: "Royalty %", f: (t) => fmtPct(t.royalty_pct) },
    has("operator") && { k: "operator", h: "Operator", align: "left", f: (t) => t.operator },
    has("lessee") && { k: "lessee", h: "Lessee", align: "left", f: (t) => t.lessee },
  ].filter(Boolean);
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 6 }}>Tracts · {tracts.length}</div>
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ ...TH, textAlign: "left" }}>Tract</th>
              {cols.map((c) => <th key={c.k} style={{ ...TH, textAlign: c.align || "right" }}>{c.h}</th>)}
            </tr>
          </thead>
          <tbody>
            {tracts.map((t, i) => (
              <tr key={t.name || i} style={{ borderTop: i ? `1px solid ${C.borderSubtle}` : "none" }}>
                <td style={{ padding: "5px 8px", fontWeight: 550, color: C.textPrimary }}>
                  {t.name || "—"}
                  {t.legal_description ? <div style={{ fontSize: 10.5, fontWeight: 400, color: C.textDim }}>{t.legal_description}</div> : null}
                </td>
                {cols.map((c) => (
                  <td key={c.k} style={{ padding: "5px 8px", textAlign: c.align || "right", fontVariantNumeric: "tabular-nums", color: c.align === "left" ? C.textDim : C.textBody }}>
                    {c.f(t) ?? "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Documents — collapsible folder groups ───────────────────────────────────
function DocFolder({ group }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <div onClick={() => setOpen((o) => !o)} style={{ display: "grid", gridTemplateColumns: "14px 1fr auto auto", gap: 10, alignItems: "center", padding: "6px 12px", cursor: "pointer", borderTop: `1px solid ${C.borderSubtle}`, background: open ? C.panelMute : "transparent" }}>
        <span style={{ color: C.accent, fontFamily: C.mono, fontSize: 11 }}>{open ? "▾" : "▸"}</span>
        <span style={{ fontSize: 12.5, fontWeight: 500, color: C.textPrimary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{group.folder}</span>
        <span style={{ fontSize: 11, color: C.textDim }}>{group.categories}</span>
        <span style={{ fontSize: 12, color: C.textMuted, fontVariantNumeric: "tabular-nums" }}>{group.count} file{group.count === 1 ? "" : "s"}</span>
      </div>
      {open ? (
        <div style={{ padding: "7px 12px 10px 36px", borderTop: `1px solid ${C.borderSubtle}`, background: C.panelMute, display: "grid", gridTemplateColumns: "1fr 1fr", gap: "3px 22px" }}>
          {group.files.map((f) => (
            <div key={f} style={{ fontSize: 11.5, color: C.textBody, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ── The viewer ──────────────────────────────────────────────────────────────
function DataroomViewer({ title, tldr, data }) {
  const deal = data.deal || {};
  const stats = data.stats || {};
  const manifest = data.manifest || [];
  const tracts = data.tracts || [];
  const documents = data.documents || [];
  const flags = data.flags || [];
  const [notesOpen, setNotesOpen] = useState(false);

  const contextLine = [deal.seller, deal.broker, deal.basin, deal.state].filter(Boolean).join(" · ");
  const tag = [deal.category, deal.asset_type].filter(Boolean).join(" · ");
  const due = deal.bid_due_date ? daysUntil(deal.bid_due_date) : null;
  const totalWells = manifest.reduce((s, g) => s + g.well_count, 0);
  const wiRange = stats.wi_min_pct != null && stats.wi_max_pct != null && stats.wi_min_pct !== stats.wi_max_pct
    ? `${fmtPct(stats.wi_min_pct)} – ${fmtPct(stats.wi_max_pct)}` : null;

  const tiles = [
    stats.well_count != null && ["Wells", fmtInt(stats.well_count)],
    stats.tract_count != null && ["Tracts", fmtInt(stats.tract_count)],
    stats.net_boed != null && ["Net prod", fmtInt(stats.net_boed), "boe/d"],
    stats.seller_pv10_mm != null && ["Seller PV10", `$${stats.seller_pv10_mm.toFixed(2)}MM`, "seller-stated"],
    stats.ltm_net_revenue_mo != null && ["LTM net rev", `${fmtCompact(stats.ltm_net_revenue_mo)}/mo`, "pre-opex, net"],
    stats.avg_wi_pct != null && ["Avg WI", fmtPct(stats.avg_wi_pct), wiRange],
    stats.doc_count != null && ["Documents", fmtInt(stats.doc_count)],
  ].filter(Boolean).slice(0, 6);

  const ltmFootnote = data.ltm_window
    ? `LTM net revenue = check-stub / LOS net revenue ${data.ltm_window.start} → ${data.ltm_window.end}, net to the extracted interest, pre-opex. Bar = share of package LTM net revenue.`
    : null;

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden", fontFamily: "Inter, system-ui, sans-serif" }}>
      {/* HEADER */}
      <div style={{ padding: "18px 20px", borderBottom: `1px solid ${C.border}`, background: C.panelMute }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ ...LBL, color: C.accent }}>Dataroom · extraction{deal.process_type ? ` · ${deal.process_type}` : ""}</div>
            <div style={{ fontSize: 23, fontWeight: 680, color: C.textPrimary, marginTop: 6, lineHeight: 1.2 }}>{title}</div>
            {contextLine ? <div style={{ fontSize: 12.5, color: C.textMuted, marginTop: 4 }}>{contextLine}</div> : null}
          </div>
          <div style={{ textAlign: "right", flex: "none", display: "flex", flexDirection: "column", gap: 7, alignItems: "flex-end" }}>
            {tag ? (
              <span style={{ fontFamily: C.mono, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", color: C.accent, border: `1px solid ${C.accent}`, borderRadius: 5, padding: "3px 8px" }}>{tag}</span>
            ) : null}
            {deal.bid_due_date ? (
              <span style={{ ...LBL, color: due != null && due <= 7 && due >= 0 ? C.flag : C.textDim }}>
                Bid due {fmtDay(deal.bid_due_date)}{due != null && due >= 0 ? ` · ${due} day${due === 1 ? "" : "s"}` : ""}
              </span>
            ) : null}
            {deal.effective_date ? <span style={{ fontSize: 11, color: C.textDim }}>Effective {fmtDay(deal.effective_date)}</span> : null}
          </div>
        </div>
        {tldr ? <div style={{ fontSize: 12.5, color: C.textBody, lineHeight: 1.55, marginTop: 12, maxWidth: 640 }}>{tldr}</div> : null}
        {tiles.length ? <div style={{ marginTop: 14 }}><StatTiles tiles={tiles} /></div> : null}
      </div>

      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 18 }}>
        {flags.length ? <Flags flags={flags} /> : null}

        {manifest.length ? (
          <div>
            <div style={{ ...LBL, marginBottom: 6 }}>Well manifest · by status</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {manifest.map((g) => (
                <ManifestGroup key={g.status} group={g} defaultOpen={totalWells <= 8} />
              ))}
            </div>
            {ltmFootnote ? <div style={{ fontSize: 10.5, color: C.textDim, marginTop: 6 }}>{ltmFootnote}</div> : null}
          </div>
        ) : null}

        {tracts.length ? <TractsTable tracts={tracts} /> : null}

        {documents.length ? (
          <div>
            <div style={{ ...LBL, marginBottom: 6 }}>Documents{stats.doc_count != null ? ` · ${stats.doc_count}` : ""}</div>
            <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflow: "hidden" }}>
              {documents.map((g) => <DocFolder key={g.folder} group={g} />)}
            </div>
          </div>
        ) : null}

        {data.notes ? (
          <div style={{ borderTop: `1px solid ${C.borderSubtle}`, paddingTop: 10 }}>
            <div onClick={() => setNotesOpen((o) => !o)} style={{ cursor: "pointer", display: "flex", gap: 8, alignItems: "baseline" }}>
              <span style={{ color: C.accent, fontFamily: C.mono, fontSize: 11 }}>{notesOpen ? "▾" : "▸"}</span>
              <span style={LBL}>Extraction notes — the data-quality record</span>
            </div>
            {notesOpen ? (
              <div style={{ fontSize: 11.5, color: C.textMuted, lineHeight: 1.55, marginTop: 7, whiteSpace: "pre-wrap" }}>{data.notes}</div>
            ) : null}
          </div>
        ) : null}
      </div>

      <div style={{ padding: "9px 20px", borderTop: `1px solid ${C.borderSubtle}`, fontSize: 10.5, color: C.textDim }}>
        Every number above is a field from the extraction or a deterministic rollup computed by the extraction kit;
        the persisted record keeps full row-level detail and per-record provenance.
      </div>
    </div>
  );
}

// ── Fill these three in. Everything above is frozen. ────────────────────────
const DATA = null;  /* paste viewer_payload.py's output verbatim */
const TITLE = "";   /* short deal title — DATA.deal.title is usually right */
const TLDR = "";    /* 1–2 sentences you write: what the package is, what to look at first */

export default function App() {
  return <DataroomViewer title={TITLE} tldr={TLDR} data={DATA} />;
}
