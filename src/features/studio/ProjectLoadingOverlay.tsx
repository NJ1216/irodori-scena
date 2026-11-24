import { createPortal } from "react-dom";

export function ProjectLoadingOverlay({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return createPortal(
    <div className="modal-backdrop project-loading-backdrop" role="status" aria-live="assertive" aria-label="プロジェクトを読み込み中">
      <div className="boot-card project-loading-card">
        <span className="project-loading-mark" aria-hidden="true">
          🌸
        </span>
        <span>
          <strong>プロジェクトを読み込んでいます…</strong>
          <small>台本と音声の準備が完了するまでお待ちください。</small>
        </span>
      </div>
    </div>,
    document.body,
  );
}
