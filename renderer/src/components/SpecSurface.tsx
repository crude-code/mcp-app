import { useEffect, useState } from "react";
import { AgentChrome, AgentWorkingBody } from "@/components/AgentContainer";
import { SpecRenderer } from "@/widgets";
import type { Agent, AgentState } from "@/types";

interface SpecSurfaceProps {
  agent: Agent;
  briefingToken?: string;
  errorMessage?: string | null;
  app?: any;
}

function extractText(res: any): string {
  const content = res?.content;
  if (Array.isArray(content)) {
    return content.filter((b: any) => b?.type === "text").map((b: any) => b.text).join("");
  }
  return typeof content === "string" ? content : "";
}

export function SpecSurface({ agent, briefingToken, errorMessage, app }: SpecSurfaceProps) {
  const [spec, setSpec] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(errorMessage ?? null);

  useEffect(() => {
    setError(errorMessage ?? null);
  }, [errorMessage]);

  useEffect(() => {
    if (!briefingToken || !app?.callServerTool) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await app.callServerTool({
          name: "get_briefing_full",
          arguments: { token: briefingToken },
        });
        if (cancelled) return;
        const parsed = JSON.parse(extractText(res) || "{}");
        if (parsed.error) setError(parsed.error);
        else setSpec(parsed.spec);
      } catch (e: any) {
        if (!cancelled) setError(e?.message ?? "failed to load briefing");
      }
    })();
    return () => { cancelled = true; };
  }, [briefingToken, app]);

  const state: AgentState = error ? "error" : spec ? "done" : "working";

  return (
    <AgentChrome agent={agent} state={state} errorMessage={error}>
      {state === "working" ? (
        <AgentWorkingBody message="Loading briefing…" />
      ) : state === "done" ? (
        <div style={{ padding: 12 }}>
          <SpecRenderer spec={spec} app={app} />
        </div>
      ) : null}
    </AgentChrome>
  );
}
