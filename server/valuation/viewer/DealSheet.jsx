// Crude Code deal sheet — frozen artifact template.
// Paste run_valuation's `data` into DATA at the bottom; write TITLE and TLDR.
// Do not restyle or restructure. Dependencies: react, recharts only.
//
// The sheet is data-driven: the evidence modules (producing fits, type
// curves) render only when `data.evidence` carries entries of that kind, so
// an all-PDP deal never shows an empty type-curve module and a legacy run
// without evidence renders the headline sheet alone.
import { useState } from "react";
import {
  LineChart as ReLineChart, Line,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
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
  accent: "#0e7490",        // selected segment / total / committed curve
  accentSoft: "#e6f2f5",    // selected queue row
  accentFg: "#ffffff",
  up: "#059669",            // oil line, positive cashflow
  down: "#dc2626",          // gas line, capex
  ink: "#1f2937",           // kept analogs, residual outliers
  ghost: "#c3c7cd",         // excluded analogs, history line
  histDot: "#9aa0a8",
  flag: "#b45309",          // off-trend / thin-cohort callouts
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
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sign}$${Math.round(a / 1e3)}K`;
  return `${sign}$${Math.round(a)}`;
};
const fmtInt = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-US"));
const fmtVol = (v) => (v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}K` : String(Math.round(v)));
const monthDiff = (a, b) => {
  // whole months from 'YYYY-MM' a to 'YYYY-MM' b
  const [ay, am] = String(a).split("-").map(Number);
  const [by, bm] = String(b).split("-").map(Number);
  return (by - ay) * 12 + (bm - am);
};
const LBL = {
  fontFamily: C.mono, fontSize: 10, letterSpacing: "0.13em",
  textTransform: "uppercase", color: C.textDim, fontWeight: 600,
};
const TILE_K = { ...LBL, fontSize: 8.5 };

// Widest the sheet is allowed to get. Nothing here is width-aware — inline
// style objects can't carry media queries, so every grid is a fixed fraction
// and every font a fixed px. Left uncapped, a shared artifact renders at full
// browser width (~1400px+) instead of the chat panel's ~700, and the two
// viewBox charts — aspect-locked, `width: 100%` — scale their labels and
// strokes with the container while the surrounding type does not. The charts
// race ahead of the text around them. Cap the card and they can't.
const SHEET_W = 1040;

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

function Rationale({ assertion }) {
  if (!assertion) {
    return <div style={{ fontSize: 12, color: C.textDim, fontStyle: "italic" }}>Committed before evidence capture — no assertion record on this run.</div>;
  }
  return (
    <div style={{ borderLeft: `3px solid ${C.accent}`, background: C.panelMute, padding: "9px 12px", borderRadius: "0 6px 6px 0" }}>
      <div style={{ ...LBL, fontSize: 9, marginBottom: 4 }}>Analyst rationale</div>
      <div style={{ fontSize: 12.5, color: C.textBody, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>{assertion.rationale || "—"}</div>
      {assertion.struck_months?.length ? (
        <div style={{ fontSize: 11, color: C.textDim, marginTop: 6 }}>
          Struck months (excluded from the read): {assertion.struck_months.join(", ")}
        </div>
      ) : null}
    </div>
  );
}

// ── Producing-well fit chart: history vs the committed curve, semilog, with a
//    residual strip over the months the curve claims to describe. Owned SVG —
//    the glued residual panel and anchor/struck annotations don't fit a chart
//    library's layout model. ─────────────────────────────────────────────────
function logTicksM(lo, hi, mantissas) {
  const out = [];
  for (let k = -1; k <= 7; k++) mantissas.forEach((m) => {
    const v = m * Math.pow(10, k);
    if (v > lo && v < hi) out.push(v);
  });
  return out;
}
const logTicks = (lo, hi) => logTicksM(lo, hi, [1, 2, 5]);

// Tick set thinned by range, not by renderer collision: mantissas drop as the
// span widens so the axis never silently hides every other label.
function axisLogTicks(lo, hi) {
  for (const ms of [[1, 2, 5], [1, 5], [1]]) {
    const t = logTicksM(lo, hi, ms);
    if (t.length <= 7) return t;
  }
  return logTicksM(lo, hi, [1]);
}

function fitDiagnostics(entry, stream) {
  // Residuals over the overlap window: reported actuals vs the committed curve.
  const hist = entry.hist, curve = entry.curve;
  if (!hist || !curve || !curve.overlap_months) return { residuals: [], flag: false, worst: 0, outside: 0 };
  const anchorIdx = hist.months.length ? monthDiff(hist.months[0], curve.start_month) : -1;
  const residuals = [];
  for (let j = 0; j < curve.overlap_months; j++) {
    const hi = anchorIdx + j;
    if (hi < 0 || hi >= hist.months.length) continue;
    const actual = hist[stream][hi], model = curve[stream][j];
    if (model > 0 && actual != null) {
      residuals.push({ m: hist.months[hi], pct: (actual / model - 1) * 100 });
    }
  }
  const worst = residuals.reduce((w, r) => Math.max(w, Math.abs(r.pct)), 0);
  const outside = residuals.filter((r) => Math.abs(r.pct) > 20).length;
  const tail = residuals.slice(-3);
  const tailMean = tail.length ? tail.reduce((s, r) => s + r.pct, 0) / tail.length : 0;
  return { residuals, worst, outside, flag: residuals.length >= 3 && Math.abs(tailMean) > 20 };
}

function WellFitChart({ entry, stream }) {
  const hist = entry.hist, curve = entry.curve;
  if (!hist || !hist.months.length) return null;
  const diag = fitDiagnostics(entry, stream);
  const showStrip = diag.residuals.length >= 4;
  const unit = stream === "oil" ? "bbl/mo" : "mcf/mo";
  const struck = new Set(entry.assertion?.struck_months || []);

  const anchorIdx = monthDiff(hist.months[0], curve ? curve.start_month : hist.months[hist.months.length - 1]);
  const nHist = hist.months.length;
  const curveLen = curve ? curve[stream].length : 0;
  const nTotal = Math.max(nHist, anchorIdx + curveLen);

  const W = 760, HM = 280, HR = showStrip ? 92 : 0, H = HM + HR;
  const PL = 52, PR = 14, PT = 12, PB = 24;
  const vals = [...hist[stream], ...(curve ? curve[stream] : [])].filter((v) => v > 0);
  if (!vals.length) return null;
  const lo = Math.min(...vals) * 0.7, hi = Math.max(...vals) * 1.3;
  const X = (i) => PL + (i / Math.max(nTotal - 1, 1)) * (W - PL - PR);
  const L = Math.log(lo), span = Math.log(hi) - L;
  const Y = (v) => HM - PB - ((Math.log(Math.max(v, lo)) - L) / span) * (HM - PT - PB);
  const k = [];

  // forecast region shading: everything past the last reported month
  const xb = X(nHist - 1);
  k.push(<rect key="fz" x={xb} y={PT - 6} width={Math.max(W - PR - xb, 0)} height={HM - PB - PT + 6} fill="#f2f7f9" />);
  logTicks(lo, hi).forEach((t) => {
    k.push(<line key={`g${t}`} x1={PL} y1={Y(t)} x2={W - PR} y2={Y(t)} stroke={C.borderSubtle} strokeWidth={1} />);
    k.push(<text key={`gt${t}`} x={PL - 6} y={Y(t) + 3.5} textAnchor="end" fontSize={9.5} fill={C.textDim}>{fmtVol(t)}</text>);
  });
  const step = nTotal > 48 ? 12 : 6;
  for (let i = 0; i < nTotal; i += step) {
    k.push(<text key={`xt${i}`} x={X(i)} y={HM - PB + 13} textAnchor="middle" fontSize={9.5} fill={C.textDim}>{fmtDate(i < nHist ? hist.months[i] : curve ? addMonths(curve.start_month, i - anchorIdx) : "")}</text>);
  }
  k.push(<line key="ax" x1={PL} y1={HM - PB} x2={W - PR} y2={HM - PB} stroke={C.border} strokeWidth={1} />);
  k.push(<text key="yl" x={PL - 6} y={PT + 1} textAnchor="end" fontSize={9} fill={C.textDim}>{unit}</text>);
  k.push(<text key="fl" x={xb + 6} y={PT + 6} fontSize={9.5} fill={C.textMuted}>forecast →</text>);

  // history: line + dots; struck months drawn hollow
  const histPath = hist.months.map((m, i) => {
    const v = hist[stream][i];
    return `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(Math.max(v, lo)).toFixed(1)}`;
  }).join(" ");
  k.push(<path key="h" d={histPath} fill="none" stroke={C.ghost} strokeWidth={1.2} />);
  hist.months.forEach((m, i) => {
    const v = Math.max(hist[stream][i], lo);
    k.push(struck.has(m)
      ? <circle key={`hd${i}`} cx={X(i)} cy={Y(v)} r={2.6} fill={C.surface} stroke={C.flag} strokeWidth={1.2} />
      : <circle key={`hd${i}`} cx={X(i)} cy={Y(v)} r={1.8} fill={C.histDot} />);
  });

  if (curve) {
    // anchor marker
    if (anchorIdx >= 0 && anchorIdx < nTotal) {
      k.push(<line key="anch" x1={X(anchorIdx)} y1={PT - 6} x2={X(anchorIdx)} y2={HM - PB} stroke={C.accent} strokeWidth={1.1} strokeDasharray="2 3" />);
      k.push(<text key="anchl" x={X(anchorIdx) + 4} y={HM - PB - 6} fontSize={9.5} fill={C.accent}>anchor</text>);
    }
    const seg = (from, to, dashed) => {
      let d = "";
      for (let j = from; j < to; j++) {
        const x = anchorIdx + j;
        if (x < 0) continue;
        d += `${d ? "L" : "M"}${X(x).toFixed(1)} ${Y(Math.max(curve[stream][j], lo)).toFixed(1)}`;
      }
      return d ? <path key={`c${from}-${dashed}`} d={d} fill="none" stroke={C.accent} strokeWidth={dashed ? 1.9 : 2.3} strokeDasharray={dashed ? "6 4" : undefined} /> : null;
    };
    const ov = curve.overlap_months || 0;
    k.push(seg(0, Math.max(ov, 1), false));
    k.push(seg(Math.max(ov - 1, 0), curveLen, true));
  }

  // residual strip
  if (showStrip) {
    const mx = Math.max(25, Math.ceil((diag.worst * 1.15) / 5) * 5);
    const RT = HM + 18, RB = H - 12, RZ = (RT + RB) / 2;
    const RY = (p) => RZ - (Math.max(-mx, Math.min(mx, p)) / mx) * ((RB - RT) / 2);
    k.push(<text key="rt" x={PL} y={RT - 5} fontSize={9.5} fill={C.textDim}>actual vs committed curve, % — over the {diag.residuals.length} overlapping months</text>);
    k.push(<line key="rz" x1={PL} y1={RZ} x2={W - PR} y2={RZ} stroke={C.border} strokeWidth={1} />);
    [20, -20].forEach((p) => {
      if (p < mx) k.push(<line key={`rg${p}`} x1={PL} y1={RY(p)} x2={W - PR} y2={RY(p)} stroke={C.borderSubtle} strokeWidth={1} strokeDasharray="3 4" />);
    });
    k.push(<text key="rl" x={PL - 6} y={RT + 3} textAnchor="end" fontSize={9} fill={C.textDim}>+{mx}%</text>);
    k.push(<text key="rl2" x={PL - 6} y={RB + 3} textAnchor="end" fontSize={9} fill={C.textDim}>−{mx}%</text>);
    diag.residuals.forEach((r) => {
      const i = hist.months.indexOf(r.m);
      const bad = Math.abs(r.pct) > 20;
      k.push(<line key={`rb${r.m}`} x1={X(i)} y1={RZ} x2={X(i)} y2={RY(r.pct)} stroke={bad ? C.ink : C.ghost} strokeWidth={2.2} />);
    });
  }

  // Capped at W: past its design width the viewBox stretch inflates every
  // label and stroke in here while the DOM type around it holds. See SHEET_W.
  return <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W, margin: "0 auto", display: "block" }}>{k}</svg>;
}

const addMonths = (ym, n) => {
  const [y, m] = String(ym).split("-").map(Number);
  const total = y * 12 + (m - 1) + n;
  return `${String(Math.floor(total / 12)).padStart(4, "0")}-${String((total % 12) + 1).padStart(2, "0")}`;
};

// ── Type-curve chart: kept analogs (normalized) behind the committed curve ──
function TypeCurveChart({ tc }) {
  const plotted = tc.kept.filter((a) => a.series && a.series.length);
  const n = Math.max(tc.series.length, ...plotted.map((a) => a.series.length), 1);
  const data = Array.from({ length: n }, (_, i) => {
    const row = { t: i + 1, curve: tc.series[i] ?? null };
    plotted.forEach((a) => { row[a.api] = a.series[i] ?? null; });
    return row;
  });
  const vals = data.flatMap((r) => Object.entries(r).filter(([kk]) => kk !== "t").map(([, v]) => v)).filter((v) => v > 0);
  if (!vals.length) return null;
  // Floor from the bulk of the data (5th percentile), never above the
  // committed curve's own minimum — one bad analog month must not drag half
  // the vertical space below everything that matters. Outliers below the
  // floor clip (allowDataOverflow), which is the honest treatment.
  const sorted = [...vals].sort((a, b) => a - b);
  const p05 = sorted[Math.floor(sorted.length * 0.05)];
  const curveMin = Math.min(...tc.series.filter((v) => v > 0));
  const lo = Math.max(Math.min(p05, curveMin) * 0.75, 0.1), hi = sorted[sorted.length - 1] * 1.3;
  const unit = tc.normalization === "per_1000ft" ? "bbl/mo per 1,000 ft" : "bbl/mo";
  return (
    <div>
      <div style={{ height: 250 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ReLineChart data={data} margin={{ top: 8, right: 10, left: 0, bottom: 0 }}>
            <XAxis dataKey="t" type="number" domain={[1, n]} tickCount={7}
              tick={{ fontSize: 9, fill: C.textDim }} tickLine={false} axisLine={{ stroke: C.border }} />
            <YAxis scale="log" domain={[lo, hi]} allowDataOverflow width={52} ticks={axisLogTicks(lo, hi)}
              tick={{ fontSize: 9, fill: C.textDim }} axisLine={false} tickLine={false}
              tickFormatter={(v) => v.toLocaleString("en-US")} />
            <Tooltip contentStyle={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 4, fontSize: 11, color: C.textPrimary }}
              labelFormatter={(t) => `month ${t}`} formatter={(v, name) => [fmtInt(v), name === "curve" ? "type curve" : (tc.kept.find((a) => a.api === name)?.name ?? name)]} />
            {plotted.map((a) => (
              <Line key={a.api} dataKey={a.api} stroke={C.ghost} strokeWidth={1.1} dot={false} isAnimationActive={false} connectNulls />
            ))}
            <Line dataKey="curve" stroke={C.accent} strokeWidth={2.6} dot={false} isAnimationActive={false} connectNulls />
          </ReLineChart>
        </ResponsiveContainer>
      </div>
      <div style={{ fontSize: 10.5, color: C.textDim, textAlign: "center", marginTop: 2 }}>
        {unit} · months on production · semilog · <span style={{ color: C.accent, fontWeight: 700 }}>—</span> committed curve
        <span style={{ color: C.ghost, fontWeight: 700 }}> —</span> {plotted.length} analogs
        {plotted.length < tc.kept.length ? ` (${tc.kept.length - plotted.length} not plotted — no lateral on record to normalize)` : ""}
      </div>
    </div>
  );
}

// ── Cohort map: static schematic in mile-space — position + lateral length,
//    not a survey plat. ───────────────────────────────────────────────────────
function CohortMap({ tc }) {
  const map = tc.map;
  if (!map || !map.subjects.length) return null;
  const wells = [
    ...tc.excluded.map((a) => ({ ...a, cls: "x" })),
    ...tc.kept.map((a) => ({ ...a, cls: "k" })),
    ...map.subjects.map((s) => ({ ...s, cls: "s" })),
  ].filter((w) => w.x != null && w.y != null);
  // A cohort map showing only the subjects says nothing — suppress it rather
  // than render a legend for wells that aren't drawn.
  if (!wells.some((w) => w.cls === "k" || w.cls === "x")) return null;

  // Fixed drawing surface; the data is projected into it. Sizing the viewBox
  // from the data and letting CSS stretch it scales every fixed-size label
  // with the extent — the giant-text failure mode. Container width does the
  // same thing, so the svg is capped at W below; see SHEET_W.
  const W = 640, H = 470, M = 24;
  const lenMi = (w) => (w.lateral_ft || 5280) / 5280;
  // Bounds cover every stick end-to-end (surface point through lateral tip),
  // and never collapse below a 2-mile window when the cohort sits on one pad.
  let x0 = Math.min(...wells.map((w) => w.x)), x1 = Math.max(...wells.map((w) => w.x));
  let y0 = Math.min(...wells.map((w) => w.y)), y1 = Math.max(...wells.map((w) => w.y + lenMi(w)));
  const MIN_EXT = 2;
  if (x1 - x0 < MIN_EXT) { const c = (x0 + x1) / 2; x0 = c - MIN_EXT / 2; x1 = c + MIN_EXT / 2; }
  if (y1 - y0 < MIN_EXT) { const c = (y0 + y1) / 2; y0 = c - MIN_EXT / 2; y1 = c + MIN_EXT / 2; }
  const S = Math.min((W - 2 * M) / (x1 - x0), (H - 2 * M) / (y1 - y0));
  const px = (x) => M + (x - x0) * S, py = (y) => H - M - (y - y0) * S;
  const k = [];
  const gridStep = Math.max(1, Math.ceil((x1 - x0) / 10), Math.ceil((y1 - y0) / 10));
  for (let i = Math.ceil(x0 / gridStep) * gridStep; i <= x1; i += gridStep)
    k.push(<line key={`gv${i}`} x1={px(i)} y1={0} x2={px(i)} y2={H} stroke={C.borderSubtle} strokeWidth={1} />);
  for (let j = Math.ceil(y0 / gridStep) * gridStep; j <= y1; j += gridStep)
    k.push(<line key={`gh${j}`} x1={0} y1={py(j)} x2={W} y2={py(j)} stroke={C.borderSubtle} strokeWidth={1} />);
  const stick = (w, key, stroke, dashed, wide) => {
    k.push(<g key={key}>
      <line x1={px(w.x)} y1={py(w.y)} x2={px(w.x)} y2={py(w.y + lenMi(w))} stroke={stroke} strokeWidth={wide ? 2.4 : 1.6} strokeDasharray={dashed ? "5 4" : undefined} />
      <circle cx={px(w.x)} cy={py(w.y)} r={2.6} fill={stroke} />
    </g>);
  };
  wells.filter((w) => w.cls === "x").forEach((a, i) => stick(a, `x${i}`, C.ghost, true, false));
  wells.filter((w) => w.cls === "k").forEach((a, i) => stick(a, `k${i}`, C.ink, false, false));
  wells.filter((w) => w.cls === "s").forEach((s, i) => stick(s, `s${i}`, C.accent, true, true));
  // Scale bar: the largest round mileage that stays inside a third of the width.
  const scaleMi = [10, 5, 2, 1, 0.5].find((m) => m * S <= W * 0.33) || 0.5;
  const sx = 16, sy = H - 14;
  k.push(<g key="scale">
    <line x1={sx} y1={sy} x2={sx + scaleMi * S} y2={sy} stroke={C.textDim} strokeWidth={1.1} />
    <line x1={sx} y1={sy - 4} x2={sx} y2={sy + 4} stroke={C.textDim} strokeWidth={1.1} />
    <line x1={sx + scaleMi * S} y1={sy - 4} x2={sx + scaleMi * S} y2={sy + 4} stroke={C.textDim} strokeWidth={1.1} />
    <text x={sx + scaleMi * S / 2} y={sy - 6} textAnchor="middle" fontSize={10} fill={C.textDim}>{scaleMi} mi</text>
  </g>);
  k.push(<g key="north">
    <text x={W - 14} y={20} textAnchor="middle" fontSize={10} fill={C.textDim}>N</text>
    <line x1={W - 14} y1={38} x2={W - 14} y2={25} stroke={C.textDim} strokeWidth={1.1} />
    <path d={`M ${W - 17.5} 29 L ${W - 14} 24 L ${W - 10.5} 29`} fill="none" stroke={C.textDim} strokeWidth={1.1} />
  </g>);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W, margin: "0 auto", display: "block", background: "#fbfbfc", border: `1px solid ${C.border}`, borderRadius: 6 }}>{k}</svg>
      <div style={{ fontSize: 10.5, color: C.textDim, marginTop: 3 }}>
        Surface position + lateral length, schematic (orientation nominal) ·{" "}
        <span style={{ color: C.accent, fontWeight: 700 }}>‑ ‑</span> subject{" "}
        <span style={{ color: C.ink, fontWeight: 700 }}>—</span> in cohort{" "}
        <span style={{ color: C.ghost, fontWeight: 700 }}>‑ ‑</span> excluded
      </div>
    </div>
  );
}

// ── Queue + detail scaffold shared by both evidence modules ──────────────────
function Queue({ entries, selId, onSelect, noteFor }) {
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflow: "auto", maxHeight: 480 }}>
      {entries.map((e) => {
        const on = e.id === selId;
        const note = noteFor(e);
        return (
          <div key={e.id} onClick={() => onSelect(e.id)}
            style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "center", padding: "8px 10px", cursor: "pointer", borderBottom: `1px solid ${C.borderSubtle}`, background: on ? C.accentSoft : "transparent", borderLeft: `3px solid ${on ? C.accent : "transparent"}` }}>
            <span style={{ minWidth: 0 }}>
              <span style={{ display: "block", fontSize: 12.5, fontWeight: 550, color: C.textPrimary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.label}</span>
              <span style={{ display: "block", fontSize: 10.5, color: C.textDim, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e._meta}</span>
            </span>
            <span style={{ textAlign: "right" }}>
              <span style={{ display: "block", fontSize: 11.5, color: C.textPrimary, fontVariantNumeric: "tabular-nums" }}>{e.pv != null ? fmtCompact(e.pv) : "—"}</span>
              {note ? <span style={{ display: "block", fontSize: 10, color: C.flag, fontWeight: 600 }}>{note}</span> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ModuleShell({ label, title, sub, open, onToggle, children }) {
  return (
    <div style={{ borderTop: `1px solid ${C.border}` }}>
      <div onClick={onToggle} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, padding: "13px 20px", cursor: "pointer" }}>
        <div>
          <div style={{ ...LBL, color: C.accent }}>{label}</div>
          <div style={{ fontSize: 15, fontWeight: 650, color: C.textPrimary, marginTop: 2 }}>{title}</div>
          <div style={{ fontSize: 11.5, color: C.textMuted, marginTop: 1 }}>{sub}</div>
        </div>
        <div style={{ ...LBL, color: C.accent, whiteSpace: "nowrap" }}>{open ? "hide −" : "open +"}</div>
      </div>
      {open ? <div style={{ padding: "0 20px 18px" }}>{children}</div> : null}
    </div>
  );
}

function MemberTable({ entry }) {
  if (!entry.wells || entry.wells.length < 2) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ ...LBL, fontSize: 9, marginBottom: 5 }}>Wells on this assertion · volumes split pro-rata on trailing-12</div>
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 6, overflow: "auto", maxHeight: 200 }}>
        {entry.wells.map((w) => (
          <div key={w.api} style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 90px 80px", gap: 8, padding: "5px 10px", borderBottom: `1px solid ${C.borderSubtle}`, fontSize: 11.5 }}>
            <span style={{ fontWeight: 500, color: C.textPrimary, whiteSpace: "nowrap", overflow: "hidden", textOverflowEllipsis: "ellipsis", textOverflow: "ellipsis" }}>{w.name}</span>
            <span style={{ color: C.textDim, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{w.operator || "—"}</span>
            <span style={{ color: C.textDim, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{w.lateral_ft ? `${fmtInt(w.lateral_ft)} ft` : "—"}</span>
            <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textPrimary }}>{w.pv != null ? fmtCompact(w.pv) : "—"}</span>
          </div>
        ))}
      </div>
      {entry.wells_more ? (
        <div style={{ fontSize: 11, color: C.textDim, marginTop: 4 }}>
          + {entry.wells_more.count} more wells{entry.wells_more.pv != null ? ` · ${fmtCompact(entry.wells_more.pv)}` : ""}
        </div>
      ) : null}
    </div>
  );
}

// ── Module 1: producing wells — history against the committed curve ─────────
function primaryStream(entry) {
  const a = entry.assertion;
  if (a?.oil) return "oil";
  if (a?.gas) return "gas";
  const oilSum = entry.hist ? entry.hist.oil.reduce((s, v) => s + v, 0) : 0;
  const gasSum = entry.hist ? entry.hist.gas.reduce((s, v) => s + v, 0) : 0;
  return gasSum > oilSum * 6 ? "gas" : "oil";
}

function ProducingPanel({ entry }) {
  const stream = primaryStream(entry);
  const diag = fitDiagnostics(entry, stream);
  const a = entry.assertion;
  const p = a?.[stream];
  const curve = entry.curve, hist = entry.hist;

  let trailing12 = null, next12 = null;
  if (hist) trailing12 = hist[stream].slice(-12).reduce((s, v) => s + v, 0);
  if (curve) {
    const ov = curve.overlap_months || 0;
    next12 = curve[stream].slice(ov, ov + 12).reduce((s, v) => s + v, 0);
  }

  const meta = [
    entry.wells[0]?.operator, entry.wells[0]?.formation,
    entry.wells.length > 1 ? `${entry.wells.length} wells` : entry.wells[0]?.county && `${entry.wells[0].county} Co.`,
    entry.pv != null && `${fmtCompact(entry.pv)} PV`,
    hist && `${hist.months.length} mo history`,
  ].filter(Boolean).join(" · ");

  const tiles = [];
  if (p) {
    tiles.push(["qi", fmtInt(p.qi), `${stream === "oil" ? "bbl" : "mcf"}/mo at anchor`]);
    tiles.push(["Di", `${(p.di * 12 * 100).toFixed(0)}%`, "nominal / yr"]);
    tiles.push(["b", p.b.toFixed(2), "hyperbolic"]);
  }
  if (a?.uptime_factor != null && a.uptime_factor !== 1) tiles.push(["uptime", `×${a.uptime_factor}`, "committed haircut"]);
  tiles.push(["anchor", entry.anchor_month ? fmtDate(entry.anchor_month) : "—", "where qi applies"]);
  if (trailing12 != null && next12 != null && trailing12 > 0) {
    tiles.push(["next 12 / trailing 12", `${Math.round((next12 / trailing12) * 100)}%`, "forecast vs actual cums"]);
  }

  return (
    <div>
      <div style={{ fontSize: 15, fontWeight: 650, color: C.textPrimary }}>{entry.label}</div>
      <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 8 }}>{meta}</div>
      {diag.flag ? (
        <div style={{ borderLeft: `3px solid ${C.flag}`, background: "#fdf7ef", padding: "7px 11px", fontSize: 12, color: C.textBody, marginBottom: 8, borderRadius: "0 6px 6px 0" }}>
          <b>This curve runs off the recent trend.</b> The last months of reported production sit
          {" "}beyond ±20% of the committed curve ({diag.outside} of {diag.residuals.length} overlapping months outside the band).
          Check for a workover, shut-in, or curtailment before accepting the forecast.
        </div>
      ) : null}
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, background: C.panelMute, padding: 8 }}>
        <WellFitChart entry={entry} stream={stream} />
      </div>
      <div style={{ display: "flex", gap: 14, marginTop: 5, fontSize: 10.5, color: C.textDim, flexWrap: "wrap" }}>
        <span><span style={{ color: C.histDot, fontWeight: 700 }}>●</span> reported monthly {stream}</span>
        <span><span style={{ color: C.accent, fontWeight: 700 }}>—</span> committed curve from anchor</span>
        <span><span style={{ color: C.accent, fontWeight: 700 }}>‑ ‑</span> forecast</span>
        {a?.struck_months?.length ? <span><span style={{ color: C.flag, fontWeight: 700 }}>○</span> struck month</span> : null}
        <span>semilog</span>
      </div>
      {tiles.length ? <div style={{ marginTop: 10 }}><StatTiles tiles={tiles.slice(0, 6)} /></div> : null}
      <div style={{ marginTop: 10 }}><Rationale assertion={a} /></div>
      <MemberTable entry={entry} />
    </div>
  );
}

// ── Module 2: type curves / undrilled locations ──────────────────────────────
function TypeCurvePanel({ entry }) {
  const tc = entry.type_curve;
  const a = entry.assertion;
  const meta = [
    `${entry.wells.length + (entry.wells_more?.count || 0)} location${entry.wells.length > 1 ? "s" : ""}`,
    entry.pv != null && `${fmtCompact(entry.pv)} PV`,
    tc?.plan_lat_ft && `${fmtInt(tc.plan_lat_ft)} ft planned lateral`,
    entry.online_month && `online ${fmtDate(entry.online_month)}`,
  ].filter(Boolean).join(" · ");

  if (!tc) {
    return (
      <div>
        <div style={{ fontSize: 15, fontWeight: 650, color: C.textPrimary }}>{entry.label}</div>
        <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 8 }}>{meta}</div>
        <div style={{ fontSize: 12, color: C.textDim, marginBottom: 10, fontStyle: "italic" }}>
          No analog cohort was recorded with this assertion — the parameters below stand on the rationale alone.
        </div>
        {a?.oil ? <StatTiles tiles={[["qi", fmtInt(a.oil.qi), "bbl/mo at online month"], ["Di", `${(a.oil.di * 12 * 100).toFixed(0)}%`, "nominal / yr"], ["b", a.oil.b.toFixed(2), "hyperbolic"]]} /> : null}
        <div style={{ marginTop: 10 }}><Rationale assertion={a} /></div>
        <MemberTable entry={entry} />
      </div>
    );
  }

  const kept = tc.kept, excl = tc.excluded;
  const thin = kept.length < 8;
  const per1k = tc.normalization === "per_1000ft";
  const cum12 = tc.series.slice(0, 12).reduce((s, v) => s + v, 0);
  const cum36 = tc.series.reduce((s, v) => s + v, 0);
  const tiles = [];
  if (a?.oil) {
    tiles.push([per1k ? "qi / 1,000 ft" : "qi", fmtInt(tc.series[0]), "bbl/mo, month 1"]);
    tiles.push(["Di", `${(a.oil.di * 12 * 100).toFixed(0)}%`, "nominal / yr"]);
    tiles.push(["b", a.oil.b.toFixed(2), "hyperbolic"]);
  }
  tiles.push(["12-mo cum", fmtInt(cum12), per1k ? "bbl per 1,000 ft" : "bbl"]);
  if (per1k && tc.plan_lat_ft) tiles.push(["36-mo / well", `${Math.round(cum36 * tc.plan_lat_ft / 1000 / 1000)} Mbbl`, `at ${fmtInt(tc.plan_lat_ft)} ft`]);
  tiles.push(["cohort", String(kept.length), "analogs kept"]);

  return (
    <div>
      <div style={{ fontSize: 15, fontWeight: 650, color: C.textPrimary }}>{entry.label}</div>
      <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 8 }}>{meta}</div>
      {thin ? (
        <div style={{ borderLeft: `3px solid ${C.flag}`, background: "#fdf7ef", padding: "7px 11px", fontSize: 12, color: C.textBody, marginBottom: 8, borderRadius: "0 6px 6px 0" }}>
          <b>Thin cohort.</b> With {kept.length} analog{kept.length === 1 ? "" : "s"}, the average moves materially if any one well is unrepresentative — read the excluded list and the rationale before accepting the curve.
        </div>
      ) : null}
      <div style={{ fontSize: 12, color: C.textBody, marginBottom: 8 }}>
        <span style={{ ...LBL, fontSize: 9 }}>Cohort filter</span>{" "}
        {tc.criteria} → <b>{kept.length} kept / {excl.length} excluded</b>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: tc.map ? "1.1fr 1fr" : "1fr", gap: 12 }}>
        <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, background: C.panelMute, padding: 8 }}>
          <TypeCurveChart tc={tc} />
        </div>
        {tc.map ? <div><CohortMap tc={tc} /></div> : null}
      </div>
      {tiles.length ? <div style={{ marginTop: 10 }}><StatTiles tiles={tiles.slice(0, 6)} /></div> : null}
      <div style={{ marginTop: 10 }}><Rationale assertion={a} /></div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
        <div>
          <div style={{ ...LBL, fontSize: 9, marginBottom: 5 }}>In the cohort · {kept.length}</div>
          <div style={{ border: `1px solid ${C.border}`, borderRadius: 6, overflow: "auto", maxHeight: 210 }}>
            {kept.map((an) => (
              <div key={an.api} style={{ display: "grid", gridTemplateColumns: "1.5fr 74px 64px 74px", gap: 8, padding: "5px 9px", borderBottom: `1px solid ${C.borderSubtle}`, fontSize: 11 }}>
                <span style={{ minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  <span style={{ fontWeight: 500, color: C.textPrimary }}>{an.name}</span>
                  <span style={{ color: C.textDim }}> · {an.operator || "—"}</span>
                </span>
                <span style={{ color: C.textDim, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{an.lateral_ft ? `${fmtInt(an.lateral_ft)}′` : "—"}</span>
                <span style={{ color: C.textDim, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{an.first_prod ? fmtDate(an.first_prod) : "—"}</span>
                <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textPrimary }}>{an.cum12_oil != null ? `${fmtVol(an.cum12_oil)} bbl` : "—"}</span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 9.5, color: C.textDim, marginTop: 3 }}>well · lateral · first prod · 12-mo cum oil</div>
        </div>
        <div>
          <div style={{ ...LBL, fontSize: 9, marginBottom: 5 }}>Excluded · {excl.length} — and why</div>
          <div style={{ border: `1px solid ${C.border}`, borderRadius: 6, overflow: "auto", maxHeight: 210 }}>
            {excl.length ? excl.map((an) => (
              <div key={an.api} style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 8, padding: "5px 9px", borderBottom: `1px solid ${C.borderSubtle}`, fontSize: 11 }}>
                <span style={{ minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  <span style={{ fontWeight: 500, color: C.textPrimary }}>{an.name}</span>
                  <span style={{ color: C.textDim }}> · {an.operator || "—"}</span>
                </span>
                <span style={{ color: C.flag, textAlign: "right", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{an.reason}</span>
              </div>
            )) : <div style={{ padding: "6px 9px", fontSize: 11, color: C.textDim }}>none recorded</div>}
          </div>
        </div>
      </div>
      <MemberTable entry={entry} />
    </div>
  );
}

function EvidenceModule({ label, title, sub, entries, Panel, noteFor, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const [selId, setSelId] = useState(entries[0]?.id);
  const sel = entries.find((e) => e.id === selId) ?? entries[0];
  const idx = entries.indexOf(sel);
  const move = (d) => setSelId(entries[(idx + d + entries.length) % entries.length].id);
  return (
    <ModuleShell label={label} title={title} sub={sub} open={open} onToggle={() => setOpen((o) => !o)}>
      <div style={{ display: "grid", gridTemplateColumns: entries.length > 1 ? "230px 1fr" : "1fr", gap: 14 }}>
        {entries.length > 1 ? (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 5 }}>
              <div style={{ ...LBL, fontSize: 9 }}>Queue · by value</div>
              <div style={{ display: "flex", gap: 4 }}>
                <button type="button" onClick={() => move(-1)} style={{ fontSize: 11, padding: "2px 8px", background: C.panelMute, border: `1px solid ${C.border}`, borderRadius: 4, cursor: "pointer", color: C.textMuted }}>←</button>
                <button type="button" onClick={() => move(1)} style={{ fontSize: 11, padding: "2px 8px", background: C.panelMute, border: `1px solid ${C.border}`, borderRadius: 4, cursor: "pointer", color: C.textMuted }}>→</button>
              </div>
            </div>
            <Queue entries={entries} selId={sel?.id} onSelect={setSelId} noteFor={noteFor} />
            <div style={{ fontSize: 10.5, color: C.textDim, marginTop: 6, lineHeight: 1.45 }}>
              Ordered by value — the assertions that move the number come first.
            </div>
          </div>
        ) : null}
        <div style={{ minWidth: 0 }}>{sel ? <Panel entry={sel} /> : null}</div>
      </div>
    </ModuleShell>
  );
}

// ── The sheet ────────────────────────────────────────────────────────────────
function DealSheet({ title, tldr, data }) {
  const { facts } = data;
  const econ = data.economics;
  const assumptions = data.assumptions || {};
  const cube = econ.cube;

  const evidence = data.evidence?.entries ?? [];
  const producing = evidence.filter((e) => e.kind === "producing")
    .map((e) => ({ ...e, _meta: [e.wells[0]?.operator, e.wells[0]?.formation, e.wells.length > 1 ? `${e.wells.length} wells` : null].filter(Boolean).join(" · ") }));
  const undrilled = evidence.filter((e) => e.kind === "undrilled")
    .map((e) => ({ ...e, _meta: [`${e.wells.length + (e.wells_more?.count || 0)} locations`, e.type_curve ? `${e.type_curve.kept.length} analogs` : "no cohort recorded"].filter(Boolean).join(" · ") }));

  // Drop categories with no wells (e.g. zero permitted) — they only add noise.
  const statuses = econ.statuses.filter((s) => s.gross_wells > 0);
  const singleStatus = statuses.length === 1;
  const [deck, setDeck] = useState(econ.default_deck);
  const [rates, setRates] = useState(econ.default_rates);

  const pv = (code) => cube[deck]?.[code]?.[rates[code]] ?? 0;
  const pvByCode = Object.fromEntries(statuses.map((s) => [s.code, pv(s.code)]));
  const total = statuses.reduce((sum, s) => sum + pvByCode[s.code], 0);
  const share = (code) => (total > 0 ? Math.round((100 * pvByCode[code]) / total) : 0);

  // Sensitivity: rung r sums every present status at its own ladder's rung r.
  const rungLabels = ["Low", "Base", "High"];
  const rungTotal = (dk, r) => statuses.reduce((s, st) => s + (cube[dk]?.[st.code]?.[st.rates[r]] ?? 0), 0);
  const selRung = (() => {
    const idxs = statuses.map((s) => s.rates.indexOf(rates[s.code]));
    return idxs.every((i) => i === idxs[0]) ? idxs[0] : -1;
  })();

  const priceLine = assumptions.price_mode === "strip"
    ? `NYMEX strip${assumptions.strip_trade_date ? ` · settle ${assumptions.strip_trade_date}` : ""}`
    : assumptions.oil_price != null ? `Flat $${assumptions.oil_price}/bbl · $${assumptions.gas_price}/MMBtu` : null;
  const histSpan = (() => {
    const lens = producing.filter((e) => e.hist).map((e) => e.hist.months.length);
    if (!lens.length) return null;
    const lo = Math.min(...lens), hi = Math.max(...lens);
    return lo === hi ? `${lo} mo` : `${lo}–${hi} mo`;
  })();
  const provenance = [
    producing.length && ["Decline curves", `${producing.length} assertion${producing.length > 1 ? "s" : ""} · ${producing.reduce((s, e) => s + e.wells.length + (e.wells_more?.count || 0), 0)} producing wells`, `public monthly production${histSpan ? ` · ${histSpan} shipped` : ""}`],
    undrilled.length && ["Type curves", `${undrilled.length} curve${undrilled.length > 1 ? "s" : ""} · ${undrilled.reduce((s, e) => s + e.wells.length + (e.wells_more?.count || 0), 0)} locations`, undrilled.some((e) => e.type_curve) ? `${undrilled.reduce((s, e) => s + (e.type_curve?.kept.length || 0), 0)} analogs, analyst-selected` : "no cohorts recorded"],
    priceLine && ["Price deck", priceLine, assumptions.oil_diff || assumptions.gas_diff ? `diffs $${assumptions.oil_diff ?? 0}/bbl · $${assumptions.gas_diff ?? 0}/MMBtu` : "no differentials"],
    ["Costs", assumptions.capex_per_well ? `${fmtCompact(assumptions.capex_per_well)} D&C / well` : "no drilling capex modeled", (assumptions.opex_per_well_month || assumptions.opex_per_bbl) ? `opex ${fmtCompact(assumptions.opex_per_well_month || 0)}/well/mo + $${assumptions.opex_per_bbl ?? 0}/bbl` : "no opex modeled"],
    ["Interest", facts.interest, facts.deal_type],
  ].filter(Boolean);

  const outputTiles = [
    ...statuses.map((s) => [`${s.code} PV`, fmtCompact(pvByCode[s.code]), `${s.gross_wells} wells · ${rates[s.code]}%`]),
    assumptions.undiscounted_cashflow != null && ["Undisc. CF", fmtCompact(assumptions.undiscounted_cashflow), `${assumptions.horizon_months ?? 360}-mo horizon`],
    assumptions.net_capex_total > 0 && ["Net D&C", fmtCompact(assumptions.net_capex_total), "your share, at online months"],
  ].filter(Boolean);

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden", fontFamily: "Inter, system-ui, sans-serif", maxWidth: SHEET_W, margin: "0 auto" }}>
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

        {outputTiles.length > 1 ? <div style={{ marginTop: 10 }}><StatTiles tiles={outputTiles.slice(0, 6)} /></div> : null}

        {/* value-share bar — only meaningful when value splits across categories */}
        {!singleStatus && (
          <div style={{ display: "flex", height: 8, borderRadius: 5, overflow: "hidden", marginTop: 14 }}>
            {statuses.map((s) => (
              <div key={s.code} style={{ background: STATUS_DOT[s.code], width: `${share(s.code)}%` }} />
            ))}
          </div>
        )}
      </div>

      {/* PV BY STATUS + SENSITIVITY */}
      <div style={{ padding: "14px 20px" }}>
        <div style={{ display: "grid", gridTemplateColumns: evidence.length ? "1.35fr 1fr" : "1fr", gap: 24 }}>
          <div>
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

          {evidence.length ? (
            <div>
              <div style={{ ...LBL, marginBottom: 10 }}>PV sensitivity · deck × discount rung</div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left", padding: "4px 6px", ...LBL, fontSize: 8.5 }}>Deck</th>
                    {rungLabels.map((r) => <th key={r} style={{ textAlign: "right", padding: "4px 6px", ...LBL, fontSize: 8.5 }}>{r}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {econ.decks.map((dk) => (
                    <tr key={dk} style={{ borderTop: `1px solid ${C.borderSubtle}` }}>
                      <td style={{ padding: "6px 6px", fontWeight: 550, color: C.textPrimary }}>{dk}</td>
                      {rungLabels.map((_, r) => {
                        const on = dk === deck && r === selRung;
                        return (
                          <td key={r} style={{ padding: "6px 6px", textAlign: "right", fontVariantNumeric: "tabular-nums", background: on ? C.accentSoft : "transparent", fontWeight: on ? 700 : 400, color: C.textPrimary }}>
                            {fmtCompact(rungTotal(dk, r))}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ fontSize: 10.5, color: C.textDim, marginTop: 5 }}>Each rung applies every category's own ladder (e.g. Base = PDP 15 / DUC 20 / PUD 25). Shaded = current selection.</div>

              <div style={{ ...LBL, margin: "16px 0 8px" }}>Value by assertion</div>
              {evidence.slice(0, 8).map((e) => (
                <div key={e.id} style={{ display: "grid", gridTemplateColumns: "1fr 76px 44px", gap: 8, alignItems: "center", fontSize: 11.5, padding: "4px 0", borderBottom: `1px solid ${C.borderSubtle}` }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: C.textPrimary }}>
                      {e.label} <span style={{ color: C.textDim }}>· {e.kind === "producing" ? "fit" : "type curve"}</span>
                    </div>
                    <div style={{ height: 4, background: C.borderSubtle, borderRadius: 2, marginTop: 3 }}>
                      <div style={{ height: "100%", background: C.accent, borderRadius: 2, width: `${Math.max((e.pv_share ?? 0) * 100, 1)}%` }} />
                    </div>
                  </div>
                  <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textPrimary }}>{e.pv != null ? fmtCompact(e.pv) : "—"}</span>
                  <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: C.textDim }}>{e.pv_share != null ? `${Math.round(e.pv_share * 100)}%` : ""}</span>
                </div>
              ))}
              {evidence.length > 8 ? <div style={{ fontSize: 10.5, color: C.textDim, marginTop: 4 }}>+ {evidence.length - 8} more below</div> : null}
              <div style={{ fontSize: 10, color: C.textDim, marginTop: 5 }}>PV at the base case (base deck, center rates) — fixed, independent of the selectors above.</div>
            </div>
          ) : null}
        </div>

        {/* WHAT INFORMED THE MODEL */}
        <div style={{ marginTop: 6, paddingTop: 12, borderTop: `1px solid ${C.borderSubtle}` }}>
          <div style={{ ...LBL, marginBottom: 8 }}>What informed the model</div>
          <div style={{ border: `1px solid ${C.border}`, borderRadius: 7, overflow: "hidden" }}>
            {provenance.map(([input, inModel, source], i) => (
              <div key={input} style={{ display: "grid", gridTemplateColumns: "130px 1fr 1fr", gap: 10, padding: "7px 12px", borderTop: i ? `1px solid ${C.borderSubtle}` : "none", fontSize: 12 }}>
                <span style={{ fontWeight: 600, color: C.textPrimary }}>{input}</span>
                <span style={{ color: C.textBody }}>{inModel}</span>
                <span style={{ color: C.textDim }}>{source}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* EVIDENCE MODULES — each one isolates a judgment so it can be checked
          against the data behind it. Rendered only when that kind exists. */}
      {producing.length ? (
        <EvidenceModule
          label={`Module 1 · producing wells · ${producing.length} assertion${producing.length > 1 ? "s" : ""}`}
          title="History against the committed curve"
          sub={(() => {
            const pvSum = producing.reduce((s, e) => s + (e.pv || 0), 0);
            const flagged = producing.filter((e) => fitDiagnostics(e, primaryStream(e)).flag).length;
            return `${fmtCompact(pvSum)} · ${producing.reduce((s, e) => s + e.wells.length + (e.wells_more?.count || 0), 0)} wells${flagged ? ` · ${flagged} fit${flagged === 1 ? " runs" : "s run"} off trend` : ""}`;
          })()}
          entries={producing}
          Panel={ProducingPanel}
          noteFor={(e) => (fitDiagnostics(e, primaryStream(e)).flag ? "off trend" : null)}
          defaultOpen={producing.length <= 3 && !undrilled.length}
        />
      ) : null}

      {undrilled.length ? (
        <EvidenceModule
          label={`Module ${producing.length ? 2 : 1} · undrilled locations · type curves`}
          title="Cohort against the curve"
          sub={(() => {
            const pvSum = undrilled.reduce((s, e) => s + (e.pv || 0), 0);
            const locs = undrilled.reduce((s, e) => s + e.wells.length + (e.wells_more?.count || 0), 0);
            const thin = undrilled.filter((e) => e.type_curve && e.type_curve.kept.length < 8).length;
            return `${fmtCompact(pvSum)} · ${locs} locations · ${undrilled.length} curve${undrilled.length > 1 ? "s" : ""}${thin ? ` · ${thin} thin cohort${thin > 1 ? "s" : ""}` : ""}`;
          })()}
          entries={undrilled}
          Panel={TypeCurvePanel}
          noteFor={(e) => (e.type_curve ? (e.type_curve.kept.length < 8 ? "thin cohort" : null) : "no cohort")}
          defaultOpen={!producing.length && undrilled.length <= 3}
        />
      ) : null}

      {evidence.length ? (
        <div style={{ padding: "9px 20px", borderTop: `1px solid ${C.borderSubtle}`, fontSize: 10.5, color: C.textDim }}>
          Every number above is computed by the valuation engine from the committed assertions; the modules show each assertion against the data behind it.
        </div>
      ) : null}

      {data.export?.bundle_url ? (
        <div style={{ padding: "11px 20px", borderTop: `1px solid ${C.borderSubtle}`, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ fontSize: 10.5, color: C.textDim, lineHeight: 1.45, minWidth: 0 }}>
            The data behind this sheet — monthly volumes and cashflow per well, the committed curves, and a README.
          </div>
          <a href={data.export.bundle_url} target="_blank" rel="noopener noreferrer"
            style={{ fontSize: 11, fontWeight: 600, color: C.accent, textDecoration: "none", background: C.panelMute, border: `1px solid ${C.border}`, borderRadius: 4, padding: "5px 11px", whiteSpace: "nowrap" }}>
            Download data package ↓
          </a>
        </div>
      ) : null}
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
