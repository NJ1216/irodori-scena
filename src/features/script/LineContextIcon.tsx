import { LineStatusIcon } from "./LineStatusIcon";
import { TakeDownloadIcon } from "./TakeDownloadIcon";

type IconName = "add" | "replace" | "rewrite" | "seed" | "unfix" | "download" | "prune" | "clear" | "delete";

export function LineContextIcon({ name }: { name: IconName }) {
  if (name === "add" || name === "replace" || name === "rewrite") {
    return (
      <span className="line-context-glyph" aria-hidden="true">
        {{ add: "＋", replace: "↻", rewrite: "✦" }[name]}
      </span>
    );
  }
  if (name === "seed" || name === "unfix")
    return (
      <span className="line-context-status-icon">
        <LineStatusIcon name="seed" />
      </span>
    );
  if (name === "download") return <TakeDownloadIcon className="line-context-icon" />;
  return (
    <svg className="line-context-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 13h10l1-13" />
    </svg>
  );
}
