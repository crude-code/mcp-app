import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { CCApp } from "./CCApp";
import { ErrorBoundary } from "./ErrorBoundary";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <CCApp />
    </ErrorBoundary>
  </StrictMode>
);
