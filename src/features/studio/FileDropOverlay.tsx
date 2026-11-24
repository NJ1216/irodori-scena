import { fileDropMessage, type FileDropClassification } from "./fileDrop";

function DropTypeIcon({ kind }: { kind: FileDropClassification["kind"] }) {
  if (kind === "project") {
    return (
      <svg className="file-drop-icon" viewBox="0 0 64 64" aria-hidden="true">
        <path d="M17 7h22l10 10v40H17z" />
        <path d="M39 7v11h10M24 28h18M24 36h13M24 44h16" />
        <path className="file-drop-icon-accent" d="M11 21h10v17H11l-5 5V21z" />
      </svg>
    );
  }
  if (kind === "casts") {
    return (
      <svg className="file-drop-icon" viewBox="0 0 64 64" aria-hidden="true">
        <circle cx="24" cy="22" r="9" />
        <circle cx="43" cy="25" r="7" />
        <path d="M8 53c1-12 7-18 16-18s15 6 16 18zM37 39c2-3 5-5 9-5 7 0 11 6 12 16H42" />
        <path className="file-drop-icon-accent" d="M28 7h22l8 8v11M50 7v8h8" />
      </svg>
    );
  }
  return (
    <svg className="file-drop-icon" viewBox="0 0 64 64" aria-hidden="true">
      <path d="M32 7 59 55H5z" />
      <path className="file-drop-icon-accent" d="M32 23v16M32 47h.01" />
    </svg>
  );
}

export function FileDropOverlay({ drop }: { drop: FileDropClassification | null }) {
  if (!drop) return null;
  const label = drop.kind === "project" ? "SCENA 台本プロジェクト" : drop.kind === "casts" ? "SCENA キャストデータ" : "読み込みできないファイル";
  return (
    <div className="file-drop-overlay" data-kind={drop.kind} role="status">
      <div className="file-drop-card">
        <DropTypeIcon kind={drop.kind} />
        <span className="file-drop-type">{label}</span>
        <strong>{fileDropMessage(drop)}</strong>
        <small>{drop.kind === "invalid" ? "このドロップは受け付けられません" : "ここにドロップして読み込み"}</small>
      </div>
    </div>
  );
}
