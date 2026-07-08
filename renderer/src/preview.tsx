// Dev-only preview harness: renders AgentChrome in its three states with
// dummy content, hot-reloaded. Served via preview.html (never bundled).
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AgentChrome, AgentWorkingBody } from "@/components/AgentContainer";
import type { Agent } from "@/types";
import "./index.css";

const GIS_TOOL: Agent = {
  code: "GIS",
  name: "Map",
  description: "wells, units & PLSS on an interactive basemap",
};

const DUMMY = (
  <div style={{ padding: 24, color: "var(--text-body)", fontSize: 13 }}>
    Content screen — replace with the surface under iteration.
  </div>
);

function Preview() {
  return (
    <div className="flex flex-col gap-6 p-6" style={{ background: "var(--bg-page)", minHeight: "100vh" }}>
      <AgentChrome agent={GIS_TOOL} state="working">
        <AgentWorkingBody message="Working…" />
      </AgentChrome>
      <AgentChrome agent={GIS_TOOL} state="done">{DUMMY}</AgentChrome>
      <AgentChrome agent={GIS_TOOL} state="error" errorMessage="Example failure — token expired.">
        {DUMMY}
      </AgentChrome>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Preview />
  </StrictMode>
);
