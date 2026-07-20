import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { EIApp } from "./EIApp";
import { ErrorBoundary } from "./ErrorBoundary";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <EIApp />
    </ErrorBoundary>
  </StrictMode>
);
