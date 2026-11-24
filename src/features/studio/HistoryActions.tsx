import { shortcutLabel } from "../shared/platform";
type HistoryScope = "script" | "characters" | "pronunciation" | null;

export function HistoryActions({ scope, status, onUndo, onRedo }: { scope: HistoryScope; status: { canUndo: boolean; canRedo: boolean; busy: boolean }; onUndo: () => void; onRedo: () => void }) {
  if (!scope) return null;
  const blocked = status.busy;
  return (
    <div className="history-actions" aria-label={`${scope} の履歴`}>
      <button type="button" aria-label="元に戻す" className="quiet-button header-action-button" disabled={blocked || !status.canUndo} title={blocked ? "処理中は元に戻せません" : status.canUndo ? shortcutLabel("元に戻す (⌘Z)") : "元に戻せる変更はありません"} onClick={onUndo}>
        ↶ <span className="header-button-label">元に戻す</span>
      </button>
      <button type="button" aria-label="やり直す" className="quiet-button header-action-button" disabled={blocked || !status.canRedo} title={blocked ? "処理中はやり直せません" : status.canRedo ? shortcutLabel("やり直す (⌘⇧Z)") : "やり直せる変更はありません"} onClick={onRedo}>
        ↷ <span className="header-button-label">やり直す</span>
      </button>
    </div>
  );
}
