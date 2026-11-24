import { useEffect, useState } from "react";
import { listenForLineJumpInput } from "./lineJumpEvents";

export function LineJumpOverlay() {
  const [value, setValue] = useState<string | null>(null);
  useEffect(() => listenForLineJumpInput(setValue), []);
  if (value === null) return null;
  const input = value.slice(1);
  const isScene = /[A-Za-z]/.test(input);
  const label = isScene ? "シーン先頭へ移動" : "発話行へ移動";
  const accessibleLabel = isScene ? label : "発話行番号へ移動";
  return (
    <aside className="line-jump-overlay" role="status" aria-live="polite" aria-label={accessibleLabel}>
      <span className="line-jump-label">{label}</span>
      <span className={`line-jump-prefix${isScene ? " is-scene" : ""}`} aria-hidden="true">
        {isScene ? "SCENE" : "#"}
      </span>
      <input aria-label={isScene ? "移動先のシーン記号" : "移動先の発話行番号"} value={input} readOnly tabIndex={-1} />
    </aside>
  );
}
