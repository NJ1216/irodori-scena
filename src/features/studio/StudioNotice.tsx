import { NoticeText } from "../shared/overlays";

export function StudioNotice({ busy, text, exportProgress, cancellable, onCancel }: { busy: string | null; text: string; exportProgress?: { currentLine: number; totalLines: number; message: string } | null; cancellable: boolean; onCancel: () => void }) {
  const message = busy === "export" && exportProgress ? `● ${exportProgress.currentLine}/${exportProgress.totalLines} ${exportProgress.message}` : `${busy ? "● " : ""}${text}`;
  return (
    <div className="notice" role="status">
      <NoticeText key={`${busy ? "busy" : "idle"}-${message}`} text={message} />
      {cancellable && (
        <button type="button" className="button-secondary notice-cancel-button" onClick={onCancel}>
          生成をキャンセル
        </button>
      )}
    </div>
  );
}
