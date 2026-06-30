import { useState } from "react";
import type { ReactNode } from "react";
import {
  LineChart as ReLineChart, Line, BarChart as ReBarChart, Bar, Cell,
  XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";
import { Segmented, fmtUSD, fmtDate, fmtCompact, LBL } from "./valuationUI";

type StatusRow = {
  code: string; label: string; tag: string; dot: string;
  gross_wells: number; net_wells: number; rates: string[];
};
type SeriesPoint = { m: number; date: string; oil: number; gas: number; cashflow: number };
type DealSheetWidget = {
  type: "deal_sheet";
  title: string; tldr: string;
  facts: { deal_type: string; interest: string; operator: string; area: string };
  decks: string[]; default_deck: string; default_rates: Record<string, string>;
  statuses: StatusRow[];
  cube: Record<string, Record<string, Record<string, number>>>;
  production: { series: SeriesPoint[]; start_month: number; end_month: number; origin: string };
  run_id?: string;
};

export function DealSheet({ widget, app }: { widget: DealSheetWidget; app?: any }) {
  const { facts, cube, production, decks } = widget;
  const [dl, setDl] = useState<"idle" | "working" | "ok" | "error">("idle");
  const downloadExport = async () => {
    if (!app?.callServerTool || !app?.downloadFile || !widget.run_id) {
      setDl("error");
      return;
    }
    setDl("working");
    try {
      const res = await app.callServerTool({
        name: "export_valuation_xlsx",
        arguments: { run_id: widget.run_id },
      });
      const raw = Array.isArray(res?.content)
        ? res.content.filter((c: any) => c?.type === "text").map((c: any) => c.text).join("")
        : "";
      const parsed = JSON.parse(raw || "{}");
      if (parsed.error || !parsed.xlsx_base64) { setDl("error"); return; }
      const dlRes = await app.downloadFile({
        contents: [{
          type: "resource",
          resource: {
            uri: `file:///${parsed.filename}`,
            mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            blob: parsed.xlsx_base64,
          },
        }],
      });
      setDl(dlRes?.isError ? "error" : "ok");
    } catch {
      setDl("error");
    }
  };
  // Drop categories with no wells (e.g. zero permitted) — they only add noise.
  const statuses = widget.statuses.filter((s) => s.gross_wells > 0);
  const singleStatus = statuses.length === 1;
  const [deck, setDeck] = useState(widget.default_deck);
  const [rates, setRates] = useState<Record<string, string>>(widget.default_rates);
  const [view, setView] = useState<"prod" | "cash">("cash");

  const pv = (code: string) => cube[deck]?.[code]?.[rates[code]] ?? 0;
  const pvByCode = Object.fromEntries(statuses.map((s) => [s.code, pv(s.code)]));
  const total = statuses.reduce((sum, s) => sum + pvByCode[s.code], 0);
  const share = (code: string) => (total > 0 ? Math.round((100 * pvByCode[code]) / total) : 0);

  return (
    <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)", borderRadius: 10, overflow: "hidden" }}>
      {/* EXEC SUMMARY */}
      <div style={{ padding: "18px 20px", borderBottom: "1px solid var(--border-default)", background: "var(--bg-panel-mute)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={LBL}>Valuation · {widget.title}</div>
            <div style={{ marginTop: 8 }}>
              <span style={{ fontSize: 34, fontWeight: 680, color: "var(--text-primary)", lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
                {fmtUSD(total)}
              </span>
              <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: 8 }}>total value · net to your interest</span>
            </div>
            <div style={{ marginTop: 4, fontSize: 12, color: "var(--text-muted)" }}>
              {statuses.map((s) => `${s.code} ${rates[s.code]}%`).join(" · ")}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ ...LBL, marginBottom: 6 }}>Price deck</div>
            <Segmented options={decks} value={deck} onChange={setDeck} />
            <div style={{ marginTop: 10 }}>
              <button
                onClick={downloadExport}
                disabled={dl === "working"}
                style={{
                  fontSize: 11, fontWeight: 600, letterSpacing: "0.02em",
                  padding: "6px 12px", borderRadius: 6, cursor: dl === "working" ? "default" : "pointer",
                  color: "var(--text-primary)", background: "var(--bg-surface)",
                  border: "1px solid var(--border-default)",
                }}
              >
                {dl === "working" ? "Preparing…" : dl === "ok" ? "Downloaded ✓" : dl === "error" ? "Download failed" : "Download export"}
              </button>
            </div>
          </div>
        </div>

        <div style={{ fontSize: 12.5, color: "var(--text-body)", lineHeight: 1.55, marginTop: 13, maxWidth: 640 }}>
          {widget.tldr}
        </div>

        {/* facts grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 1, marginTop: 16, background: "var(--border-default)", border: "1px solid var(--border-default)", borderRadius: 7, overflow: "hidden" }}>
          {[["Deal type", facts.deal_type], ["Interest", facts.interest], ["Operator", facts.operator], ["Area", facts.area]].map(([k, v]) => (
            <div key={k} style={{ background: "var(--bg-surface)", padding: "9px 12px" }}>
              <div style={{ ...LBL, fontSize: 8.5 }}>{k}</div>
              <div style={{ fontSize: 13, color: "var(--text-primary)", marginTop: 3 }}>{v}</div>
            </div>
          ))}
        </div>

        {/* value-share bar — only meaningful when value splits across categories */}
        {!singleStatus && (
          <div style={{ display: "flex", height: 8, borderRadius: 5, overflow: "hidden", marginTop: 14 }}>
            {statuses.map((s) => (
              <div key={s.code} style={{ background: s.dot, width: `${share(s.code)}%` }} />
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
          <div key={s.code} style={{ display: "grid", gridTemplateColumns: "1.5fr auto .9fr", gap: 10, padding: "11px 0", borderTop: "1px solid var(--border-subtle)", alignItems: "center" }}>
            <div>
              <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
                <span style={{ color: s.dot }}>●</span> {s.label} <span style={{ color: "var(--text-dim)", fontSize: 12 }}>{s.tag}</span>
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 2 }}>{s.net_wells} net · {s.gross_wells} gross</div>
            </div>
            <Segmented small options={s.rates.map((r) => `${r}%`)} value={`${rates[s.code]}%`}
              onChange={(v) => setRates((prev) => ({ ...prev, [s.code]: v.replace("%", "") }))} />
            <div style={{ textAlign: "right" }}>
              <div style={{ color: "var(--text-primary)", fontSize: 14, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{fmtUSD(pvByCode[s.code])}</div>
              <div style={{ color: "var(--text-dim)", fontSize: 12 }}>{share(s.code)}%</div>
            </div>
          </div>
        ))}

        {/* The lone category IS the total — drop the redundant footer row. */}
        {!singleStatus && (
          <div style={{ display: "grid", gridTemplateColumns: "1.5fr auto .9fr", gap: 10, padding: "11px 0", borderTop: "1px solid var(--border-default)", alignItems: "center" }}>
            <div style={{ color: "var(--text-muted)", fontSize: 12, fontWeight: 600 }}>Total</div>
            <div />
            <div style={{ textAlign: "right", color: "var(--content-accent)", fontSize: 15, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{fmtUSD(total)}</div>
          </div>
        )}
      </div>

      {/* FORECAST — production volumes or net cashflow over the active window */}
      <div style={{ padding: "14px 20px", borderTop: "1px solid var(--border-default)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <div style={LBL}>Forecast</div>
          <Segmented small options={["Production", "Net Cashflow"]}
            value={view === "prod" ? "Production" : "Net Cashflow"}
            onChange={(v) => setView(v === "Production" ? "prod" : "cash")} />
        </div>
        <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 10 }}>
          {view === "prod" ? (
            <>net oil <span style={{ color: "var(--change-up)" }}>●</span>&nbsp; net gas <span style={{ color: "var(--change-down)" }}>●</span> &nbsp;·&nbsp; volumes per month, independent of the price deck</>
          ) : (
            <><span style={{ color: "var(--change-down)" }}>▮</span> CAPEX&nbsp; <span style={{ color: "var(--change-up)" }}>▮</span> Net Cashflow &nbsp;·&nbsp; net to interest, per month</>
          )}
        </div>
        <div style={{ height: 184, border: "1px solid var(--border-default)", borderRadius: 6, background: "var(--bg-panel-mute)", padding: "8px 4px" }}>
          <ResponsiveContainer width="100%" height="100%">
            {view === "prod" ? (
              <ReLineChart data={production.series} margin={{ top: 8, right: 6, left: 4, bottom: 0 }}>
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: "var(--text-dim)" }} tickLine={false}
                  axisLine={{ stroke: "var(--border-default)" }} tickFormatter={fmtDate} minTickGap={28} />
                <YAxis yAxisId="oil" tick={{ fontSize: 9, fill: "var(--change-up)" }} axisLine={false} tickLine={false} width={46}
                  label={{ value: "net oil · bbl", angle: -90, position: "insideLeft", style: { fontSize: 9, fill: "var(--change-up)", letterSpacing: "0.06em" } }} />
                <YAxis yAxisId="gas" orientation="right" tick={{ fontSize: 9, fill: "var(--change-down)" }} axisLine={false} tickLine={false} width={46}
                  label={{ value: "net gas · mcf", angle: 90, position: "insideRight", style: { fontSize: 9, fill: "var(--change-down)", letterSpacing: "0.06em" } }} />
                <Tooltip contentStyle={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)", borderRadius: 4, fontSize: 12, color: "var(--text-primary)" }}
                  labelFormatter={(d: ReactNode) => fmtDate(String(d))} />
                <Line yAxisId="oil" name="net oil (bbl)" type="monotone" dataKey="oil" stroke="var(--change-up)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line yAxisId="gas" name="net gas (mcf)" type="monotone" dataKey="gas" stroke="var(--change-down)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              </ReLineChart>
            ) : (
              <ReBarChart data={production.series} margin={{ top: 8, right: 6, left: 8, bottom: 0 }}>
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: "var(--text-dim)" }} tickLine={false}
                  axisLine={{ stroke: "var(--border-default)" }} tickFormatter={fmtDate} minTickGap={28} />
                <YAxis tick={{ fontSize: 9, fill: "var(--text-dim)" }} axisLine={false} tickLine={false} width={52} tickFormatter={fmtCompact} />
                <Tooltip contentStyle={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)", borderRadius: 4, fontSize: 12, color: "var(--text-primary)" }}
                  labelFormatter={(d: ReactNode) => fmtDate(String(d))} formatter={(v) => [fmtUSD(Number(v)), Number(v) >= 0 ? "Net Cashflow" : "CAPEX"]} />
                <ReferenceLine y={0} stroke="var(--text-dim)" />
                <Bar dataKey="cashflow" isAnimationActive={false}>
                  {production.series.map((p) => (
                    <Cell key={p.m} fill={p.cashflow >= 0 ? "var(--change-up)" : "var(--change-down)"} />
                  ))}
                </Bar>
              </ReBarChart>
            )}
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
