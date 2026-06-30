import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { Agent, AgentState } from "@/types";

interface AgentContainerProps {
  agent: Agent;
  state: AgentState;
  /** ms timestamp; defaults to mount time. */
  startedAt?: number;
  /** When state="done", whether the body starts collapsed behind the chevron. */
  defaultCollapsed?: boolean;
  children: ReactNode;
}

// "Signal instrument" chrome: dark graphite faceplate, a live level-meter that
// dances while WORKING and settles on DONE, a white light-mode screen for the
// content. Accent per state — cyan (working/done) / red (error).
// All color/font identity lives in index.css (--ac-*, --font-chrome*); only
// pure black/white depth shadows remain inline below (depth, not design).
const SG = "var(--font-chrome)";
const SM = "var(--font-chrome-mono)";
const CYAN = "var(--ac-accent)";
const CYAN_DIM = "var(--ac-accent-dim)";
const RED = "var(--ac-error)";

const accentOf = (s: AgentState) => (s === "error" ? RED : CYAN);
// Translucent accent glow — derived from the accent's RGB token so a theme
// change to the accent propagates here automatically.
const glowOf = (s: AgentState, a: number) =>
  `rgb(${s === "error" ? "var(--ac-error-rgb)" : "var(--ac-accent-rgb)"} / ${a})`;

const STATUS_LABEL: Record<AgentState, string> = {
  working: "WORKING",
  done: "DONE",
  error: "ERROR",
};

function elapsedLabel(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

// The level meter. Dances while working; freezes to a captured reading on done;
// flatlines red on error.
const BAR_H = [16, 22, 14, 24, 18, 26, 15, 21];
function SignalBars({ state }: { state: AgentState }) {
  const running = state === "working";
  const error = state === "error";
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 2.5, height: 26, padding: "0 11px", borderLeft: "1px solid rgba(255,255,255,.06)", borderRight: "1px solid rgba(255,255,255,.06)", flexShrink: 0 }}>
      {BAR_H.map((h, i) => (
        <span key={i} style={{
          width: 3, borderRadius: 1, transformOrigin: "bottom",
          height: error ? 3 : h,
          background: error ? RED : running ? CYAN : i >= 5 ? "var(--ac-bar-idle)" : CYAN,
          boxShadow: error ? `0 0 5px ${glowOf("error", 0.6)}` : running || i < 5 ? `0 0 6px ${glowOf(state, 0.55)}` : "none",
          animation: running ? `signal-eq ${0.46 + (i % 4) * 0.13}s ease-in-out ${i * 0.06}s infinite alternate` : "none",
        }} />
      ))}
    </div>
  );
}

function StatusReadout({ state, elapsed }: { state: AgentState; elapsed: string }) {
  if (state === "done") {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: SM, fontSize: 12, fontWeight: 700, color: "var(--ac-pill-text)", background: "var(--ac-pill-bg)", border: "1px solid var(--ac-pill-border)", borderRadius: 5, padding: "6px 10px", boxShadow: `inset 0 1px 0 rgba(255,255,255,.4), 0 0 12px ${glowOf("done", 0.28)}`, flexShrink: 0 }}>
        <span style={{ letterSpacing: "0.04em" }}>{elapsed}</span>
        <span style={{ width: 1, height: 12, background: "var(--ac-pill-divider)" }} />
        <span style={{ letterSpacing: "0.08em" }}>DONE</span>
      </div>
    );
  }
  const accent = accentOf(state);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: SM, fontSize: 12, fontWeight: 700, color: accent, background: glowOf(state, 0.08), border: `1px solid ${state === "error" ? RED : CYAN_DIM}`, borderRadius: 5, padding: "6px 10px", flexShrink: 0 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: accent, boxShadow: `0 0 8px ${accent}`, animation: state === "working" ? "signal-pulse 1.2s ease-in-out infinite" : "none" }} />
      <span style={{ letterSpacing: "0.08em" }}>{STATUS_LABEL[state]}</span>
      {state === "working" && <span style={{ color: "var(--ac-meta)", fontWeight: 400 }}>{elapsed}</span>}
    </div>
  );
}

export function AgentContainer({
  agent,
  state,
  startedAt,
  defaultCollapsed = false,
  children,
}: AgentContainerProps) {
  const [mountTime] = useState(() => startedAt ?? Date.now());
  const [now, setNow] = useState(() => Date.now());
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  // Tick the elapsed counter only while working; freeze on done/error.
  useEffect(() => {
    if (state !== "working") return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [state]);

  const running = state === "working";
  const isDone = state === "done";
  const accent = accentOf(state);
  const elapsed = elapsedLabel(now - mountTime);

  return (
    <div style={{ fontFamily: SG, background: "var(--ac-panel-bg)", borderRadius: 13, overflow: "hidden", border: "1px solid var(--ac-panel-border)", boxShadow: "inset 0 1px 0 rgba(120,180,200,.10), inset 0 0 0 1px rgba(255,255,255,.015), 0 24px 56px -28px rgba(0,0,0,.7)", padding: 14, position: "relative" }}>
      {/* faint cyan grid wash on the faceplate */}
      <div style={{ position: "absolute", inset: 0, backgroundImage: `linear-gradient(${glowOf(state, 0.05)} 1px, transparent 1px), linear-gradient(90deg, ${glowOf(state, 0.05)} 1px, transparent 1px)`, backgroundSize: "22px 22px", maskImage: "linear-gradient(180deg, rgba(0,0,0,.6), transparent 70%)", WebkitMaskImage: "linear-gradient(180deg, rgba(0,0,0,.6), transparent 70%)", pointerEvents: "none" }} />

      {/* HEADER */}
      <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 13, padding: "3px 5px 14px" }}>
        {/* emblem — concentric dial with live core */}
        <div style={{ width: 38, height: 38, borderRadius: 9, background: "var(--ac-emblem-bg)", border: "1px solid var(--ac-line)", display: "grid", placeItems: "center", boxShadow: "inset 0 1px 1px rgba(150,210,230,.14), inset 0 0 10px rgba(0,0,0,.6)", flexShrink: 0 }}>
          <span style={{ width: 16, height: 16, borderRadius: "50%", border: `1.5px solid ${state === "error" ? RED : CYAN_DIM}`, display: "grid", placeItems: "center" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: accent, boxShadow: `0 0 8px ${accent}, 0 0 14px ${glowOf(state, 0.5)}`, animation: running ? "signal-pulse 1.2s ease-in-out infinite" : "none" }} />
          </span>
        </div>

        {/* name + role */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: SG, fontSize: 16.5, fontWeight: 700, letterSpacing: "-0.01em", color: "var(--ac-title)", lineHeight: 1.1 }}>{agent.name}</div>
          {agent.description && (
            <div style={{ fontFamily: SM, fontSize: 9.5, letterSpacing: "0.05em", color: "var(--ac-muted)", marginTop: 5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{agent.description.toUpperCase()}</div>
          )}
        </div>

        <SignalBars state={state} />
        <StatusReadout state={state} elapsed={elapsed} />

        {isDone && (
          <button
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand" : "Collapse"}
            style={{ background: "var(--ac-button-bg)", border: "1px solid var(--ac-line)", color: "var(--ac-button-text)", padding: "4px 8px", borderRadius: 5, cursor: "pointer", fontFamily: SM, fontSize: 11, lineHeight: 1, flexShrink: 0 }}
          >
            {collapsed ? "▾" : "▴"}
          </button>
        )}
      </div>

      {/* WHITE SCREEN — the content body, light mode */}
      {!collapsed && (
        <div style={{ position: "relative", background: "var(--ac-screen)", borderRadius: 8, border: "1px solid var(--ac-screen-border)", boxShadow: `inset 0 0 0 1px ${glowOf(state, 0.1)}, 0 2px 0 rgba(0,0,0,.25)`, overflow: "hidden" }}>
          <div style={{ height: 3, background: `linear-gradient(90deg, ${accent}, ${state === "error" ? "var(--ac-error-dim)" : CYAN_DIM} 60%, transparent)` }} />
          {children}
        </div>
      )}
    </div>
  );
}

/**
 * Compact body shown while an agent is working with no streaming feed. Spinner
 * + status text, on white.
 */
export function AgentWorkingBody({ message }: { message: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 16px" }}>
      <div style={{ width: 14, height: 14, borderRadius: "50%", border: "2px solid var(--border-default)", borderTopColor: CYAN, animation: "spin 0.8s linear infinite", flexShrink: 0 }} />
      <span style={{ fontFamily: "var(--font-sans)", fontSize: 13, color: "var(--text-muted)" }}>{message}</span>
    </div>
  );
}

/**
 * Outer shell for any tool-result invocation. Owns the AgentContainer and the
 * standard working/error states — callers only supply the body for
 * state="done" via children.
 */
export function AgentChrome({
  agent,
  state,
  errorMessage,
  children,
}: {
  agent: Agent;
  state: AgentState;
  errorMessage?: string | null;
  children?: ReactNode;
}) {
  return (
    <AgentContainer agent={agent} state={state}>
      {state === "working" && (children ?? <AgentWorkingBody message="Working…" />)}
      {state === "error" && (
        <div style={{ padding: "14px 16px", fontFamily: "var(--font-sans)", fontSize: 13, color: "var(--change-down)" }}>
          {errorMessage}
        </div>
      )}
      {state === "done" && children}
    </AgentContainer>
  );
}
