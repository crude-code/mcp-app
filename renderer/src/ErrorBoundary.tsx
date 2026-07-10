import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Renderer crashed:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="w-full flex items-center justify-center min-h-[200px]"
          style={{ background: "var(--bg-page)" }}
        >
          <div style={{ color: "var(--error)", fontSize: 14 }}>
            Something went wrong rendering this view.
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
