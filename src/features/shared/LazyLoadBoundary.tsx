import { Component, type ReactNode } from "react";

export class LazyLoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="boot-card" role="alert">
        画面を読み込めませんでした。
        <button type="button" className="secondary" onClick={() => window.location.reload()}>
          再読み込み
        </button>
      </div>
    );
  }
}
