import ErrorState from "./ui/ErrorState";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled render error:", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;

    return (
      <ErrorState
        size="page"
        title="Something went wrong"
        description="The page stopped unexpectedly. Reloading usually clears it. Nothing you had already saved is affected."
        retryLabel="Reload the page"
        onRetry={() => window.location.reload()}
      />
    );
  }
}
