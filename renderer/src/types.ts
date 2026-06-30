// Cross-cutting types shared across renderer components. Component-internal
// prop types stay alongside their component.

export interface Agent {
  code: string; // 2-letter code, e.g. "DB"
  name: string; // "Briefing", "Portal Agent"
  description?: string; // one-line tagline shown under the name (static label, not telemetry)
}

export type AgentState = "working" | "done" | "error";
