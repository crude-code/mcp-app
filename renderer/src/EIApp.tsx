import { useState, useCallback, useEffect } from "react";
import type { McpUiHostContext } from "@modelcontextprotocol/ext-apps";
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { MapView } from "./components/MapView";

function extractText(result: any): string {
  if (Array.isArray(result?.content)) {
    return result.content
      .filter((c: any) => c.type === "text")
      .map((c: any) => c.text || "")
      .join("");
  }
  if (typeof result?.content === "string") return result.content;
  if (typeof result?.text === "string") return result.text;
  if (typeof result === "string") return result;
  return "";
}

function tryParse(raw: string): any | null {
  try {
    return JSON.parse(raw);
  } catch {
    const match = raw.match(/\{[\s\S]*\}/);
    if (!match) return null;
    try {
      return JSON.parse(match[0]);
    } catch {
      return null;
    }
  }
}

export function EIApp() {
  const [mapToken, setMapToken] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [hostContext, setHostContext] = useState<McpUiHostContext | undefined>();

  const onAppCreated = useCallback((createdApp: any) => {
    createdApp.onhostcontextchanged = (params: any) => {
      setHostContext((prev) => ({ ...prev, ...params }));
    };
    createdApp.onerror = console.error;

    createdApp.ontoolresult = (params: any) => {
      const raw = extractText(params);
      if (!raw) return;
      const parsed = tryParse(raw);
      if (!parsed) return;
      if (parsed.error) {
        // Server errors may carry a user-friendly `message` alongside the raw
        // code (e.g. at_capacity) — prefer it for the card.
        setError(parsed.message ?? parsed.error);
        return;
      }
      if (parsed.map_token) {
        setMapToken(parsed.map_token);
        setError(null);
      }
    };
  }, []);

  const { app, isConnected, error: connError } = useApp({
    appInfo: { name: "Crude Code", version: "2.0.0" },
    capabilities: {},
    onAppCreated,
    autoResize: false,
  });

  useEffect(() => {
    if (!app) return;
    setHostContext(app.getHostContext());
  }, [app]);

  useEffect(() => {
    if (!app) return;
    return app.setupSizeChangedNotifications();
  }, [app]);

  if (connError) {
    return (
      <div
        className="w-full flex items-center justify-center min-h-[200px]"
        style={{ background: "var(--bg-page)" }}
      >
        <div style={{ color: "var(--change-down)", fontSize: 14 }}>
          Connection error: {connError.message}
        </div>
      </div>
    );
  }

  const toolName = hostContext?.toolInfo?.tool?.name as string | undefined;

  if (isConnected && toolName === "map") {
    return (
      <div className="w-full" style={{ background: "var(--bg-page)" }}>
        <MapView mapToken={mapToken} app={app} errorMessage={error} />
      </div>
    );
  }

  return (
    <div
      className="w-full flex items-center justify-center min-h-[200px]"
      style={{ background: "var(--bg-page)" }}
    >
      <div style={{ color: "var(--text-dim)", fontSize: 14 }}>
        {!isConnected ? "Connecting..." : "Loading..."}
      </div>
    </div>
  );
}
