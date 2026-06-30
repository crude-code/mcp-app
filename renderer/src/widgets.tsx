/** Shared spec-driven briefing renderer.
 *
 * A briefing spec shape:
 *   { headline?: string, tldr?: string, sections: [...] }
 *
 * Each section: { label?, layout: "full-width"|"2-col"|"3-col", widgets: [...] }
 *
 * Widget types: commentary | callout | table | line_chart | bar_chart
 */

import { useState } from "react";
import type { FC } from "react";
import {
  LineChart as ReLineChart,
  Line,
  BarChart as ReBarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { DealSheet } from "./components/DealSheet";
import { AdvancedView } from "./components/AdvancedView";
import { Segmented } from "./components/valuationUI";

const LAYOUT_CLASSES: Record<string, string> = {
  "2-col": "grid grid-cols-2 gap-3",
  "2-col-40-60": "grid grid-cols-[2fr_3fr] gap-3",
  "3-col": "grid grid-cols-3 gap-3",
  "full-width": "flex flex-col gap-3",
};

const MULTI_SERIES_COLORS = [
  "var(--content-accent)",
  "var(--change-up)",
  "var(--accent-blue)",
  "var(--accent-purple)",
];

/**
 * Strip the time component from ISO-style x-axis values so charts show
 * just the date. `"2025-06-02 00:00:00+00:00"` → `"2025-06-02"`.
 * Non-date strings pass through untouched.
 */
const stripTime = (val: any): string => {
  if (typeof val !== "string") return String(val);
  const m = val.match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : val;
};

const TONE_BORDERS: Record<string, string> = {
  neutral: "var(--border-default)",
  bullish: "var(--change-up)",
  bearish: "var(--change-down)",
  warning: "var(--content-accent)",
};

// ── BriefingHeader ──────────────────────────────────────────────────────────

export function BriefingHeader({
  headline,
  tldr,
}: {
  headline?: string;
  tldr?: string;
}) {
  if (!headline && !tldr) return null;

  return (
    <div style={{ marginBottom: 18 }}>
      {headline && (
        <div
          style={{
            fontFamily: "var(--font-heading)",
            fontSize: 20,
            fontWeight: 600,
            color: "var(--text-primary)",
            lineHeight: 1.3,
            marginBottom: tldr ? 8 : 0,
          }}
        >
          {headline}
        </div>
      )}
      {tldr && (
        <div
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 13.5,
            lineHeight: 1.55,
            color: "var(--text-muted)",
            maxWidth: 720,
          }}
        >
          {tldr}
        </div>
      )}
    </div>
  );
}

// ── CommentaryWidget ────────────────────────────────────────────────────────

export function CommentaryWidget({ widget }: { widget: any }) {
  const tone = widget.tone || "neutral";
  const accent = TONE_BORDERS[tone] || TONE_BORDERS.neutral;
  return (
    <div
      style={{
        background: "var(--bg-surface)",
        borderLeft: `3px solid ${accent}`,
        padding: "12px 16px",
        borderRadius: "0 3px 3px 0",
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 13.5,
          lineHeight: 1.6,
          color: "var(--text-primary)",
          whiteSpace: "pre-wrap",
        }}
      >
        {widget.text}
      </div>
    </div>
  );
}

// ── CalloutWidget ───────────────────────────────────────────────────────────

// Commodity semantic color: oil → green, gas → red.
const OIL_CODES = new Set(["WTI_USD", "BRENT_CRUDE_USD"]);
const GAS_CODES = new Set(["NATURAL_GAS_USD"]);

function commodityColor(code: string | undefined): string {
  if (code && OIL_CODES.has(code)) return "var(--change-up)";
  if (code && GAS_CODES.has(code)) return "var(--change-down)";
  return "var(--text-primary)";
}

// Pull a "$/bbl"-style unit out of the label (e.g. "WTI Crude $/bbl") so we
// can render it dim+small alongside the bold ticker name. Returns [name, unit].
function splitLabelUnit(raw: string): [string, string | null] {
  const m = raw.match(/^(.+?)\s+(\$\/[A-Za-z]+)\s*$/);
  if (m) return [m[1], m[2]];
  return [raw, null];
}

export function CalloutWidget({ widget }: { widget: any }) {
  const rawLabel = widget.label || "";
  const value = widget.value ?? "—";
  const delta = widget.delta;
  const deltaPct = widget.delta_pct ?? extractPct(delta);
  const deltaDir = widget.delta_direction;
  const sparkline: { x: string; y: number }[] = Array.isArray(widget.sparkline) ? widget.sparkline : [];
  const footnote = widget.footnote;
  const [name, unit] = splitLabelUnit(rawLabel);

  const changeColor =
    deltaDir === "up"
      ? "var(--change-up)"
      : deltaDir === "down"
        ? "var(--change-down)"
        : "var(--text-muted)";
  const arrow = deltaDir === "up" ? "▲" : deltaDir === "down" ? "▼" : "◆";

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: sparkline.length > 0 ? "1fr 110px" : "1fr",
        gap: 12,
        alignItems: "center",
        padding: "10px 14px",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "0.1em",
            color: "var(--text-muted)",
            textTransform: "uppercase",
            marginBottom: 2,
            display: "flex",
            alignItems: "baseline",
            gap: 6,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          <span>{name}</span>
          {unit && (
            <span style={{ color: "var(--text-dim)", fontSize: 9 }}>{unit}</span>
          )}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 8,
            fontVariantNumeric: "tabular-nums",
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 18,
              fontWeight: 700,
              letterSpacing: "-0.01em",
              color: "var(--text-primary)",
            }}
          >
            {value}
          </span>
          {(deltaPct || delta) && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                fontWeight: 600,
                color: changeColor,
              }}
            >
              {arrow} {deltaPct ?? delta}
            </span>
          )}
        </div>
        {footnote && (
          <div
            style={{
              marginTop: 4,
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-dim)",
              letterSpacing: "0.2px",
            }}
          >
            {footnote}
          </div>
        )}
      </div>

      {sparkline.length > 0 && (
        <div style={{ height: 38 }}>
          <ResponsiveContainer width="100%" height="100%">
            <ReLineChart data={sparkline} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
              <Line
                type="monotone"
                dataKey="y"
                stroke={commodityColor(widget.code)}
                strokeWidth={1.4}
                dot={false}
                isAnimationActive={false}
              />
            </ReLineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// Pull "+1.2%" out of a delta string like "+0.31 (+0.3%)" — the more
// compact "▲ 0.31%" form reads better at the inline width than the
// dollar-and-percent combo the hydrator emits.
function extractPct(delta: string | undefined): string | null {
  if (!delta) return null;
  const m = delta.match(/\(([+-]?[\d.]+%)\)/);
  return m ? m[1] : null;
}

// ── TableWidget ─────────────────────────────────────────────────────────────

const TABLE_DISPLAY_CAP = 50;

function inferAlign(rows: any[], key: string): "left" | "right" {
  const sample = rows.slice(0, 5).map((r) => r[key]);
  const numeric = sample.every((v) => v == null || typeof v === "number");
  return numeric && sample.some((v) => v != null) ? "right" : "left";
}

export function TableWidget({ widget }: { widget: any }) {
  const columns: any[] = Array.isArray(widget.columns) ? widget.columns : [];
  const rowsAll: any[] = Array.isArray(widget.rows) ? widget.rows : [];
  const truncated = rowsAll.length > TABLE_DISPLAY_CAP;
  const rows = truncated ? rowsAll.slice(0, TABLE_DISPLAY_CAP) : rowsAll;
  const remaining = rowsAll.length - rows.length;

  return (
    <div
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border-default)",
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      {widget.label && (
        <div
          style={{
            padding: "10px 14px",
            background: "var(--bg-panel-mute)",
            borderBottom: "1px solid var(--border-default)",
            fontFamily: "var(--font-heading)",
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "1.5px",
            textTransform: "uppercase",
            color: "var(--text-dim)",
          }}
        >
          {widget.label}
        </div>
      )}
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontFamily: "var(--font-sans)",
            fontSize: 12.5,
          }}
        >
          <thead>
            <tr>
              {columns.map((col) => {
                const align = col.align || inferAlign(rows, col.key);
                return (
                  <th
                    key={col.key}
                    style={{
                      textAlign: align,
                      padding: "8px 14px",
                      fontFamily: "var(--font-mono)",
                      fontSize: 10,
                      fontWeight: 600,
                      letterSpacing: "1px",
                      textTransform: "uppercase",
                      color: "var(--text-muted)",
                      borderBottom: "1px solid var(--border-default)",
                    }}
                  >
                    {col.label || col.key}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((col) => {
                  const align = col.align || inferAlign(rows, col.key);
                  const isNum = align === "right";
                  const cell = row[col.key];
                  return (
                    <td
                      key={col.key}
                      style={{
                        textAlign: align,
                        padding: "7px 14px",
                        color: "var(--text-primary)",
                        borderBottom: i < rows.length - 1 ? "1px solid var(--border-faint)" : "none",
                        fontVariantNumeric: isNum ? "tabular-nums" : "normal",
                        fontFamily: isNum ? "var(--font-mono)" : "var(--font-sans)",
                        whiteSpace: col.nowrap ? "nowrap" : "normal",
                      }}
                    >
                      {cell == null ? "—" : String(cell)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(truncated || widget.footnote) && (
        <div
          style={{
            padding: "8px 14px",
            borderTop: "1px solid var(--border-default)",
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-dim)",
          }}
        >
          {truncated && `+${remaining} more row${remaining === 1 ? "" : "s"} not shown`}
          {truncated && widget.footnote && " · "}
          {widget.footnote}
        </div>
      )}
    </div>
  );
}

// ── LineChartWidget ─────────────────────────────────────────────────────────

export function LineChartWidget({ widget }: { widget: any }) {
  const data = Array.isArray(widget.data) ? widget.data : [];
  // Normalize: a string entry (legacy / non-canonical) is treated as a key
  // with the same string as its label. The skill validator now rejects
  // strings, but the renderer stays forgiving so any in-flight or
  // hand-edited spec still draws.
  const seriesArr: any[] | undefined = Array.isArray(widget.series)
    ? widget.series.map((s: any) => (typeof s === "string" ? { key: s, label: s } : s))
    : undefined;
  const series = seriesArr ?? [{ key: "y", label: widget.label || "value" }];

  return (
    <div
      className="p-4 relative overflow-hidden"
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border-default)",
        borderRadius: 4,
      }}
    >
      <div
        className="absolute top-0 left-0 w-full h-0.5"
        style={{ background: "var(--content-accent)", opacity: 0.4 }}
      />
      {widget.label && (
        <div
          className="mb-3"
          style={{
            fontFamily: "var(--font-heading)",
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "1.5px",
            textTransform: "uppercase",
            color: "var(--text-dim)",
          }}
        >
          {widget.label}
        </div>
      )}
      <div className="h-[180px] -mx-1">
        <ResponsiveContainer width="100%" height="100%">
          <ReLineChart data={data} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
            <XAxis
              dataKey="x"
              tick={{ fontSize: 10, fill: "var(--text-dim)" }}
              axisLine={{ stroke: "var(--border-default)" }}
              tickLine={false}
              minTickGap={20}
              tickFormatter={stripTime}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--text-dim)" }}
              axisLine={false}
              tickLine={false}
              width={38}
              domain={widget.y_zero ? [0, "auto"] : ["auto", "auto"]}
            />
            <Tooltip
              contentStyle={{
                background: "var(--bg-surface)",
                border: "1px solid var(--border-default)",
                borderRadius: 4,
                fontSize: "12px",
                color: "var(--text-primary)",
              }}
              cursor={{ stroke: "var(--border-default)", strokeWidth: 1 }}
              labelFormatter={stripTime}
            />
            {seriesArr && seriesArr.length > 1 && (
              <Legend wrapperStyle={{ fontSize: 11, color: "var(--text-dim)" }} />
            )}
            {series.map((s, i) => (
              <Line
                key={s.key}
                name={s.label || s.key}
                type="monotone"
                dataKey={s.key}
                stroke={s.color || MULTI_SERIES_COLORS[i % MULTI_SERIES_COLORS.length]}
                strokeWidth={2}
                strokeDasharray={s.dashed ? "4 4" : undefined}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </ReLineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── BarChartWidget ──────────────────────────────────────────────────────────

export function BarChartWidget({ widget }: { widget: any }) {
  const data = Array.isArray(widget.data) ? widget.data : [];
  const horizontal = widget.orientation === "horizontal";

  return (
    <div
      className="p-4 relative overflow-hidden"
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border-default)",
        borderRadius: 4,
      }}
    >
      <div
        className="absolute top-0 left-0 w-full h-0.5"
        style={{ background: "var(--content-accent)", opacity: 0.4 }}
      />
      {widget.label && (
        <div
          className="mb-3"
          style={{
            fontFamily: "var(--font-heading)",
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "1.5px",
            textTransform: "uppercase",
            color: "var(--text-dim)",
          }}
        >
          {widget.label}
        </div>
      )}
      <div className="h-[200px] -mx-1">
        <ResponsiveContainer width="100%" height="100%">
          <ReBarChart
            data={data}
            layout={horizontal ? "vertical" : "horizontal"}
            margin={{ top: 5, right: 8, left: horizontal ? 40 : 0, bottom: 0 }}
          >
            <XAxis
              type={horizontal ? "number" : "category"}
              dataKey={horizontal ? undefined : "x"}
              tick={{ fontSize: 10, fill: "var(--text-dim)" }}
              axisLine={{ stroke: "var(--border-default)" }}
              tickLine={false}
              tickFormatter={horizontal ? undefined : stripTime}
            />
            <YAxis
              type={horizontal ? "category" : "number"}
              dataKey={horizontal ? "x" : undefined}
              tick={{ fontSize: 10, fill: "var(--text-dim)" }}
              axisLine={false}
              tickLine={false}
              width={horizontal ? 80 : 38}
              tickFormatter={horizontal ? stripTime : undefined}
            />
            <Tooltip
              contentStyle={{
                background: "var(--bg-surface)",
                border: "1px solid var(--border-default)",
                borderRadius: 4,
                fontSize: "12px",
                color: "var(--text-primary)",
              }}
              cursor={{ fill: "var(--border-default)", opacity: 0.2 }}
              labelFormatter={stripTime}
            />
            <Bar dataKey="y" fill="var(--content-accent)" isAnimationActive={false} />
          </ReBarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── UnknownWidget ───────────────────────────────────────────────────────────

export function UnknownWidget({ widget }: { widget: any }) {
  return (
    <div
      className="p-4"
      style={{
        background: "var(--bg-surface)",
        border: "1px dashed var(--border-default)",
        borderRadius: 4,
        fontSize: 11,
        color: "var(--text-dim)",
      }}
    >
      Unsupported widget type:{" "}
      <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
        {String(widget?.type ?? "(missing)")}
      </span>
    </div>
  );
}

// ── SpecSection ─────────────────────────────────────────────────────────────

type WidgetProps = { widget: any; app?: any };

export const widgetRegistry: Record<string, FC<WidgetProps>> = {
  commentary: CommentaryWidget,
  callout: CalloutWidget,
  table: TableWidget,
  line_chart: LineChartWidget,
  bar_chart: BarChartWidget,
  deal_sheet: DealSheet as FC<WidgetProps>,
};

function renderWidget(widget: any, key: string | number, app?: any) {
  const Component = widgetRegistry[widget?.type];
  if (!Component) return <UnknownWidget key={key} widget={widget} />;
  return <Component key={key} widget={widget} app={app} />;
}

export function SpecSection({
  section,
  app,
}: {
  section: any;
  app?: any;
}) {
  const widgets: any[] = section.widgets ?? [];

  // Flush-row treatment: if every widget in a multi-column section is a
  // `callout`, render them without per-card chrome and separate with
  // vertical dividers — reads as a single market-snapshot strip.
  const allCallouts =
    widgets.length > 0 && widgets.every((w) => w?.type === "callout");
  const multiCol = section.layout === "2-col" || section.layout === "3-col";

  return (
    <div>
      {section.label && (
        <div className="briefing-section-label flex items-center gap-3 mb-4">
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "1.5px",
              textTransform: "uppercase",
              color: "var(--text-muted)",
            }}
          >
            {section.label}
          </span>
          <div
            className="flex-1 h-px"
            style={{ background: "var(--border-default)" }}
          />
          {section.cap_right && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--text-dim)",
              }}
            >
              {section.cap_right}
            </span>
          )}
        </div>
      )}

      {allCallouts && multiCol ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${section.layout === "2-col" ? 2 : 3}, 1fr)`,
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderRadius: 4,
          }}
        >
          {widgets.map((widget, i) => (
            <div
              key={widget.label || i}
              className="briefing-widget"
              style={{
                borderRight:
                  i < widgets.length - 1
                    ? "1px solid var(--border-default)"
                    : "none",
              }}
            >
              <CalloutWidget widget={widget} />
            </div>
          ))}
        </div>
      ) : (
        <div className={LAYOUT_CLASSES[section.layout] || LAYOUT_CLASSES["3-col"]}>
          {widgets.map((widget, i) => (
            <div key={widget.label || widget.code || i} className="briefing-widget">
              {renderWidget(widget, widget.label || widget.code || i, app)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Deal sheet surface: compact DealSheet ↔ AdvancedView toggle ─────────────
// When the spec carries an `advanced` block, a small segmented control swaps
// between the compact deal sheet and the advanced "Behind the Valuation" view.
// Specs without `advanced` (older runs) render the deal sheet unchanged.

function DealSheetSurface({ spec, widget, app }: { spec: any; widget: any; app?: any }) {
  const [view, setView] = useState<"Deal sheet" | "Advanced">("Deal sheet");
  if (!spec.advanced) return <DealSheet widget={widget} app={app} />;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <Segmented options={["Deal sheet", "Advanced"]} value={view} onChange={(v) => setView(v as "Deal sheet" | "Advanced")} small />
      </div>
      {view === "Deal sheet"
        ? <DealSheet widget={widget} app={app} />
        : <AdvancedView advanced={spec.advanced} headlineNpv={spec.headline_npv} />}
    </div>
  );
}

// ── SpecRenderer (root) ─────────────────────────────────────────────────────

interface SpecRendererProps {
  spec: any;
  app?: any;
}

export function SpecRenderer({ spec, app }: SpecRendererProps) {
  if (!spec) return null;
  const sections: any[] = Array.isArray(spec.sections) ? spec.sections : [];

  // Deal sheet: a single self-contained widget that renders its own header,
  // facts, and sections — skip BriefingHeader + section chrome.
  if (spec.layout === "deal_sheet") {
    const widget = sections[0]?.widgets?.[0];
    if (!widget) return null;
    return <DealSheetSurface spec={spec} widget={widget} app={app} />;
  }

  return (
    <div>
      <BriefingHeader
        headline={spec.headline}
        tldr={spec.tldr}
      />
      <div className="space-y-5">
        {sections.map((section: any, i: number) => (
          <SpecSection
            key={section.label || i}
            section={section}
            app={app}
          />
        ))}
      </div>
    </div>
  );
}
