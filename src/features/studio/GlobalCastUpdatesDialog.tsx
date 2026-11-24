import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";

export function GlobalCastUpdatesDialog({ characters, busy, onKeepProject, onApply }: { characters: Array<{ id: string; name: string }>; busy: boolean; onKeepProject: () => void; onApply: () => void }) {
  return (
    <ModalBackdrop onClose={onKeepProject} disabled={busy}>
      <section className="modal global-cast-updates-dialog" role="dialog" aria-modal="true" aria-label="グローバルキャストの更新">
        <DialogHeader eyebrow="GLOBAL CAST UPDATE" title="最新のグローバルキャストがあります" description="このプロジェクトで使用中のキャストに更新があります。グローバル版を適用すると、キャスト情報・参照ボイス・画像を最新の内容に更新します。" />
        <ul>
          {characters.map((character) => (
            <li key={character.id}>{character.name || "名称未設定のキャスト"}</li>
          ))}
        </ul>
        <DialogFooter>
          <button type="button" disabled={busy} onClick={onKeepProject}>
            プロジェクト版を維持
          </button>
          <button className="primary" disabled={busy} onClick={onApply}>
            {busy ? "適用中…" : "グローバル版を適用"}
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
