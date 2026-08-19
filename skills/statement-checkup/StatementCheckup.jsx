// Crude Code statement checkup — frozen artifact template.
// Paste checkup_payload.py's output into DATA at the bottom; write TITLE and
// TLDR. Do not restyle or restructure. Dependencies: react only.
//
// The viewer is a plain-English health report on one revenue statement, for
// an individual mineral/royalty owner — not an analyst. It is data-driven:
// every module renders only when the payload carries its data — no public
// volumes → the statement-vs-state columns disappear, no findings → no
// checkup block, no questions → no questions panel. Every number is a line
// item from the statement or a deterministic rollup computed by
// checkup_payload.py — nothing here or in the fill step does arithmetic.
import { useState } from "react";

// ── Palette — matches the deal-sheet / dataroom templates (siblings), plus a
//    calm green for checks that pass: a checkup needs a "healthy" color. ────
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
  taxBar: "#9ca3af",
  mono: "ui-monospace, SFMono-Regular, Menlo, monospace",
};
const LBL = {
  fontFamily: C.mono, fontSize: 10, letterSpacing: "0.13em",
  textTransform: "uppercase", color: C.textDim, fontWeight: 600,
};
const TILE_K = { ...LBL, fontSize: 8.5 };
const TH = { ...LBL, fontSize: 8.5, textAlign: "right", padding: "4px 8px", whiteSpace: "nowrap" };

const SEVERITY = {
  attention: { chip: "needs a look", color: C.flag, bg: C.flagBg },
  info: { chip: "worth knowing", color: C.accent, bg: C.accentSoft },
  good: { chip: "looks good", color: C.ok, bg: C.okSoft },
};
const BADGE = {
  ok: { text: "✓ matches", color: C.ok },
  shrink: { text: "shrink", color: C.textDim },
  ask: { text: "worth asking", color: C.flag },
};

// Royalty checks are cent-sized money: always show cents.
const fmtUSD = (v) => (v == null ? "—" :
  `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const fmtInt = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-US"));
const fmtNum = (v) => (v == null ? "—" : v.toLocaleString("en-US"));
const fmtSignedPct = (v) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`);
const fmtCents = (v) => (v == null ? "—" : `${v < 0 ? "−" : ""}${(Math.round(Math.abs(v) * 10) / 10).toLocaleString("en-US")}¢`);
// Full precision on the ownership decimal — it is the multiplier on every
// dollar; rounding it here would make the viewer disagree with the statement.
const fmtDecimal = (v) => (v == null ? "—" : String(v));
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtDay = (d) => {
  if (!d) return "—";
  const [y, m, day] = String(d).split("-").map(Number);
  return `${MONTHS[m - 1] ?? ""} ${day ?? ""}, ${y}`;
};
const fmtMonth = (m) => {
  const [y, mo] = String(m).split("-").map(Number);
  return `${MONTHS[mo - 1] ?? ""} ${y}`;
};

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

// ── The checkup — findings with a verdict line ──────────────────────────────
function Findings({ findings, verdict }) {
  const counts = [
    verdict.attention ? `${verdict.attention} needs a look` : null,
    verdict.info ? `${verdict.info} worth knowing` : null,
    verdict.good ? `${verdict.good} look${verdict.good === 1 ? "s" : ""} good` : null,
  ].filter(Boolean).join(" · ");
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 8 }}>The checkup{counts ? ` · ${counts}` : ""}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {findings.map((f, i) => {
          const s = SEVERITY[f.severity] || SEVERITY.info;
          return (
            <div key={i} style={{ display: "flex", gap: 10, padding: "8px 10px", background: s.bg, border: `1px solid ${C.borderSubtle}`, borderRadius: 7 }}>
              <span style={{ fontFamily: C.mono, fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: s.color, fontWeight: 700, flex: "none", width: 88, paddingTop: 2 }}>{s.chip}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 650, color: C.textPrimary }}>{f.title}</div>
                <div style={{ fontSize: 12.5, color: C.textBody, lineHeight: 1.5, marginTop: 2 }}>{f.body}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Where the money went — one bar, then the itemized charges ───────────────
function MoneyFlow({ money }) {
  const segs = [
    { label: "You kept", amount: money.net, pctv: money.net_pct, color: C.accent },
    { label: "Taxes", amount: money.taxes, pctv: money.taxes_pct, color: C.taxBar },
    { label: "Deductions", amount: money.deductions, pctv: money.deductions_pct, color: C.flag },
  ].filter((s) => s.amount != null && s.pctv != null && s.pctv > 0);
  const maxItem = Math.max(1, ...money.tax_items.map((i) => Math.abs(i.amount)), ...money.deduction_items.map((i) => Math.abs(i.amount)));
  const ItemCol = ({ heading, total, items }) => (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 12, fontWeight: 650, color: C.textPrimary, marginBottom: 4 }}>
        {heading} <span style={{ fontWeight: 400, color: C.textDim }}>· {fmtUSD(total)}</span>
      </div>
      {items.map((it) => (
        <div key={it.label} style={{ display: "grid", gridTemplateColumns: "1fr 70px 64px", gap: 8, alignItems: "center", padding: "2px 0" }}>
          <span style={{ fontSize: 11.5, color: C.textBody, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{it.label}</span>
          <div style={{ height: 5, background: C.barTrack, borderRadius: 2 }}>
            <div style={{ height: "100%", background: it.amount < 0 ? C.ok : C.textDim, borderRadius: 2, width: `${Math.max(1.5, (Math.abs(it.amount) / maxItem) * 100)}%` }} />
          </div>
          <span style={{ fontSize: 11.5, color: it.amount < 0 ? C.ok : C.textMuted, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
            {it.amount < 0 ? `+${fmtUSD(-it.amount)}` : fmtUSD(it.amount)}
          </span>
        </div>
      ))}
    </div>
  );
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 8 }}>Where the money went · of {fmtUSD(money.gross)} gross</div>
      <div style={{ display: "flex", height: 18, borderRadius: 5, overflow: "hidden", border: `1px solid ${C.border}` }}>
        {segs.map((s) => (
          <div key={s.label} style={{ width: `${s.pctv}%`, background: s.color }} title={`${s.label}: ${fmtUSD(s.amount)} (${s.pctv}%)`} />
        ))}
      </div>
      <div style={{ display: "flex", gap: 18, marginTop: 5, flexWrap: "wrap" }}>
        {segs.map((s) => (
          <span key={s.label} style={{ fontSize: 11.5, color: C.textMuted, display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: s.color, display: "inline-block" }} />
            {s.label} {fmtUSD(s.amount)} · {s.pctv}%
          </span>
        ))}
      </div>
      {money.non_revenue_deductions ? (
        <div style={{ fontSize: 11.5, color: C.textMuted, marginTop: 5 }}>
          Plus {fmtUSD(money.non_revenue_deductions)} of non-revenue deductions netted from the check.
        </div>
      ) : null}
      {!money.ties_out && money.mismatches?.length ? (
        <div style={{ marginTop: 8, padding: "7px 10px", background: C.flagBg, border: `1px solid ${C.flag}`, borderRadius: 6, fontSize: 11.5, color: C.flag, lineHeight: 1.5 }}>
          <b>The statement's line items don't reproduce its own printed totals:</b> {money.mismatches.join("; ")}
        </div>
      ) : null}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 28px", marginTop: 12 }}>
        <ItemCol heading="Taxes" total={money.taxes} items={money.tax_items} />
        <ItemCol heading="Deductions" total={money.deductions} items={money.deduction_items} />
      </div>
    </div>
  );
}

// ── By product — netbacks and price checks ──────────────────────────────────
function ProductTable({ products }) {
  const hasBench = products.some((p) => p.benchmark);
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 6 }}>By product · your share</div>
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ ...TH, textAlign: "left" }}>Product</th>
              <th style={TH}>Your volume</th>
              <th style={TH}>Price</th>
              {hasBench ? <th style={{ ...TH, textAlign: "left" }}>vs benchmark</th> : null}
              <th style={TH}>Revenue</th>
              <th style={TH}>Taxes</th>
              <th style={TH}>Deductions</th>
              <th style={TH}>Net to you</th>
              <th style={TH}>Kept of each $1</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p, i) => {
              const neg = p.net != null && p.net < 0;
              const b = p.benchmark;
              return (
                <tr key={p.product} style={{ borderTop: i ? `1px solid ${C.borderSubtle}` : "none" }}>
                  <td style={{ padding: "6px 8px", fontWeight: 550, color: C.textPrimary, whiteSpace: "nowrap" }}>{p.product}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textBody, whiteSpace: "nowrap" }}>{fmtNum(p.owner_volume)} {p.unit || ""}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textBody, whiteSpace: "nowrap" }}>{p.price != null ? `$${p.price.toFixed(2)}` : "—"}</td>
                  {hasBench ? (
                    <td style={{ padding: "6px 8px", fontSize: 11, color: C.textDim, whiteSpace: "nowrap" }}>
                      {b ? (b.pct_of_wti != null ? `${b.pct_of_wti}% ${b.label}` : `${b.label} $${b.value} (${fmtSignedPct(b.delta_pct)})`) : "—"}
                    </td>
                  ) : null}
                  <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textBody }}>{fmtUSD(p.revenue)}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textMuted }}>{fmtUSD(p.taxes)}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textMuted }}>{fmtUSD(p.deductions)}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600, color: neg ? C.flag : C.textPrimary }}>{fmtUSD(p.net)}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600, color: neg ? C.flag : C.ok }}>{fmtCents(p.kept_pct)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Well by well — the statement against the state's records ────────────────
function WellTable({ wells }) {
  const hasPub = wells.some((w) => w.liquids_pub != null || w.gas_pub != null);
  const Cmp = ({ stmt, pub, delta, badge }) => {
    if (pub == null) return <span style={{ color: C.textDim }}>{stmt != null ? fmtInt(stmt) : "—"}</span>;
    const b = BADGE[badge] || null;
    return (
      <span style={{ whiteSpace: "nowrap" }}>
        <span style={{ color: C.textBody }}>{fmtInt(stmt)}</span>
        <span style={{ color: C.textDim }}> / {fmtInt(pub)}</span>
        <span style={{ color: C.textDim, fontSize: 10.5 }}> {fmtSignedPct(delta)}</span>
        {b ? <span style={{ fontFamily: C.mono, fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase", color: b.color, marginLeft: 6 }}>{b.text}</span> : null}
      </span>
    );
  };
  return (
    <div>
      <div style={{ ...LBL, marginBottom: 6 }}>Well by well{hasPub ? " · statement / state records" : ""}</div>
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ ...TH, textAlign: "left" }}>Well</th>
              <th style={TH}>Net to you</th>
              <th style={{ ...TH, width: 70 }} />
              {hasPub ? <th style={{ ...TH, textAlign: "left" }}>Liquids, bbl</th> : null}
              {hasPub ? <th style={{ ...TH, textAlign: "left" }}>Gas, MCF</th> : null}
            </tr>
          </thead>
          <tbody>
            {wells.map((w, i) => (
              <tr key={w.property_id || i} style={{ borderTop: i ? `1px solid ${C.borderSubtle}` : "none" }}>
                <td style={{ padding: "5px 8px", whiteSpace: "nowrap" }}>
                  <span style={{ fontWeight: 550, color: C.textPrimary }}>{w.name}</span>
                  {w.formation ? <span style={{ fontSize: 10.5, color: C.textDim, marginLeft: 6 }}>{w.formation}</span> : null}
                </td>
                <td style={{ padding: "5px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textBody, whiteSpace: "nowrap" }}>{fmtUSD(w.net)}</td>
                <td style={{ padding: "5px 8px" }}>
                  <div style={{ height: 5, background: C.barTrack, borderRadius: 2 }}>
                    <div style={{ height: "100%", background: C.accent, borderRadius: 2, width: `${Math.max(w.share_pct ?? 0, w.share_pct != null ? 0.5 : 0)}%` }} />
                  </div>
                </td>
                {hasPub ? <td style={{ padding: "5px 8px", fontVariantNumeric: "tabular-nums" }}><Cmp stmt={w.liquids_stmt} pub={w.liquids_pub} delta={w.liquids_delta_pct} badge={w.liquids_badge} /></td> : null}
                {hasPub ? <td style={{ padding: "5px 8px", fontVariantNumeric: "tabular-nums" }}><Cmp stmt={w.gas_stmt} pub={w.gas_pub} delta={w.gas_delta_pct} badge={w.gas_badge} /></td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasPub ? (
        <div style={{ fontSize: 10.5, color: C.textDim, marginTop: 6, lineHeight: 1.5 }}>
          Liquids = oil + condensate (states report them together). The statement pays on volumes <i>sold</i>;
          the state records volumes <i>produced</i> — small gaps are tank timing. Statement gas is sold gas after
          plant shrink and fuel, so sitting below the state's wellhead number is normal when NGLs are paid separately.
        </div>
      ) : null}
    </div>
  );
}

// ── Questions to take to the operator ───────────────────────────────────────
function Questions({ questions }) {
  return (
    <div style={{ background: C.accentSoft, border: `1px solid ${C.border}`, borderRadius: 7, padding: "12px 14px" }}>
      <div style={{ ...LBL, color: C.accent, marginBottom: 8 }}>Questions worth asking your operator</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {questions.map((q, i) => (
          <div key={i} style={{ display: "flex", gap: 8, fontSize: 12.5, lineHeight: 1.5, color: C.textBody }}>
            <span style={{ fontFamily: C.mono, color: C.accent, fontWeight: 700, flex: "none" }}>{String(i + 1).padStart(2, "0")}</span>
            <span>{q}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── The viewer ──────────────────────────────────────────────────────────────
function StatementCheckup({ title, tldr, data }) {
  const h = data.header || {};
  const money = data.money;
  const dec = data.decimal_check || {};
  const [notesOpen, setNotesOpen] = useState(false);

  const monthsLine = (h.production_months || []).map(fmtMonth).join(", ");
  const contextLine = [h.operator, h.location, h.well_count ? `${h.well_count} well${h.well_count === 1 ? "" : "s"}` : null,
    monthsLine ? `production ${monthsLine}` : null].filter(Boolean).join(" · ");

  const tiles = [
    money?.gross != null && ["Gross value", fmtUSD(money.gross), "before anything came out"],
    money?.taxes != null && ["Taxes", fmtUSD(-money.taxes), money.taxes_pct != null ? `${fmtCents(money.taxes_pct)} of each $1` : null],
    money?.deductions != null && ["Deductions", fmtUSD(-money.deductions), money.deductions_pct != null ? `${fmtCents(money.deductions_pct)} of each $1` : null],
    money?.net_pct != null && ["You kept", fmtCents(money.net_pct), "of each gross $1"],
    dec.decimals?.length === 1 && ["Your decimal", fmtDecimal(dec.decimals[0]), "same on every line"],
    h.well_count != null && ["Wells", fmtInt(h.well_count)],
  ].filter(Boolean).slice(0, 6);

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden", fontFamily: "Inter, system-ui, sans-serif" }}>
      {/* HEADER */}
      <div style={{ padding: "18px 20px", borderBottom: `1px solid ${C.border}`, background: C.panelMute }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ ...LBL, color: C.accent }}>Revenue statement · checkup</div>
            <div style={{ fontSize: 23, fontWeight: 680, color: C.textPrimary, marginTop: 6, lineHeight: 1.2 }}>{title}</div>
            {contextLine ? <div style={{ fontSize: 12.5, color: C.textMuted, marginTop: 4 }}>{contextLine}</div> : null}
          </div>
          <div style={{ textAlign: "right", flex: "none" }}>
            <div style={{ fontSize: 26, fontWeight: 700, color: C.textPrimary, fontVariantNumeric: "tabular-nums" }}>{fmtUSD(h.check_amount)}</div>
            <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>
              {[h.check_number ? `check #${h.check_number}` : null, h.check_date ? fmtDay(h.check_date) : null].filter(Boolean).join(" · ")}
            </div>
            {h.interest_type ? (
              <span style={{ display: "inline-block", marginTop: 7, fontFamily: C.mono, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", color: C.accent, border: `1px solid ${C.accent}`, borderRadius: 5, padding: "3px 8px" }}>{h.interest_type}</span>
            ) : null}
          </div>
        </div>
        {tldr ? <div style={{ fontSize: 12.5, color: C.textBody, lineHeight: 1.55, marginTop: 12, maxWidth: 640 }}>{tldr}</div> : null}
        {tiles.length ? <div style={{ marginTop: 14 }}><StatTiles tiles={tiles} /></div> : null}
      </div>

      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 18 }}>
        {data.findings?.length ? <Findings findings={data.findings} verdict={data.verdict || {}} /> : null}
        {money ? <MoneyFlow money={money} /> : null}
        {data.products?.length ? <ProductTable products={data.products} /> : null}
        {data.wells?.length ? <WellTable wells={data.wells} /> : null}
        {data.questions?.length ? <Questions questions={data.questions} /> : null}

        {data.notes ? (
          <div style={{ borderTop: `1px solid ${C.borderSubtle}`, paddingTop: 10 }}>
            <div onClick={() => setNotesOpen((o) => !o)} style={{ cursor: "pointer", display: "flex", gap: 8, alignItems: "baseline" }}>
              <span style={{ color: C.accent, fontFamily: C.mono, fontSize: 11 }}>{notesOpen ? "▾" : "▸"}</span>
              <span style={LBL}>How this was checked — the fine print</span>
            </div>
            {notesOpen ? (
              <div style={{ fontSize: 11.5, color: C.textMuted, lineHeight: 1.55, marginTop: 7, whiteSpace: "pre-wrap" }}>{data.notes}</div>
            ) : null}
          </div>
        ) : null}
      </div>

      <div style={{ padding: "9px 20px", borderTop: `1px solid ${C.borderSubtle}`, fontSize: 10.5, color: C.textDim, lineHeight: 1.5 }}>
        Every number above is a line item from your statement or a deterministic rollup computed by the checkup kit
        {data.sources ? `; ${data.sources.charAt(0).toLowerCase()}${data.sources.slice(1).replace(/\.$/, "")}` : ""}.
        Informational only — not legal, tax, or investment advice.
      </div>
    </div>
  );
}

// ── Fill these three in. Everything above is frozen. ────────────────────────
const DATA = null;  /* paste checkup_payload.py's output verbatim */
const TITLE = "";   /* short title — operator + production month, e.g. "Bison IV — November 2025 check" */
const TLDR = "";    /* 1–2 sentences you write: the overall verdict in plain English */

export default function App() {
  return <StatementCheckup title={TITLE} tldr={TLDR} data={DATA} />;
}
