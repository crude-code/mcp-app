// Preview — the "signal instrument" AgentContainer wrapping REAL output: the
// valuation deal sheet / advanced view and the data-analyst briefing from
// captured fixtures, in both working and done states. Served via preview.html.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AgentChrome, AgentWorkingBody } from "@/components/AgentContainer";
import { SpecRenderer } from "@/widgets";
import type { Agent } from "@/types";
import SAMPLE_DEAL_SHEET from "@/fixtures/deal_sheet.json";
import SAMPLE_BRIEFING from "@/fixtures/briefing.json";
import "./index.css";

const VALUATION: Agent = {
  code: "VA",
  name: "Valuation Analyst",
  description: "forecasts wells & runs cashflow → PV at any discount rate",
};

const DATA_ANALYST: Agent = {
  code: "DA",
  name: "Data Analyst",
  description: "investigates wells, prices, filings & news → sourced briefings",
};

function Caption({ name, note }: { name: string; note: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 10, margin: "0 0 12px 2px" }}>
      <span style={{ fontFamily: "'Space Mono', monospace", fontSize: 11, letterSpacing: "0.18em", textTransform: "uppercase", color: "#33312c", fontWeight: 700 }}>{name}</span>
      <span style={{ fontFamily: "var(--font-sans)", fontSize: 12, color: "#7d786e" }}>{note}</span>
    </div>
  );
}

function Preview() {
  return (
    <div style={{ background: "var(--bg-page)", minHeight: "100vh", padding: "44px 0 90px" }}>
      <div style={{ maxWidth: 720, margin: "0 auto", padding: "0 16px" }}>
        <div style={{ fontFamily: "var(--font-chrome)", fontSize: 22, color: "#26241f", marginBottom: 4 }}>Valuation Analyst · signal wrapper</div>
        <div style={{ fontFamily: "var(--font-sans)", fontSize: 13, color: "#6c675d", marginBottom: 34 }}>Real deal-sheet output inside the new chrome. Meter dances while working, settles on done.</div>

        <Caption name="Working" note="signal meter live · spinner on white" />
        <AgentChrome agent={VALUATION} state="working">
          <AgentWorkingBody message="Loading briefing…" />
        </AgentChrome>

        <div style={{ height: 44 }} />

        <Caption name="Done" note="real deal sheet · toggle to Advanced for the three tabs" />
        <AgentChrome agent={VALUATION} state="done">
          <SpecRenderer spec={SAMPLE_DEAL_SHEET as any} />
        </AgentChrome>

        <div style={{ height: 44 }} />

        <Caption name="Data Analyst — done" note="briefing spec · callout + line chart + table" />
        <AgentChrome agent={DATA_ANALYST} state="done">
          <div style={{ padding: 12 }}>
            <SpecRenderer spec={SAMPLE_BRIEFING as any} />
          </div>
        </AgentChrome>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Preview />
  </StrictMode>
);
