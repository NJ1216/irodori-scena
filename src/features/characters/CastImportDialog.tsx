import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { apiFetch } from "../../api-runtime";
import type { CastImportItem, CastImportPreparation, Character, StudioProject } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { actionableCastImportConflicts, castImportResultMessage, skippedCastImportReasons } from "./castImportWorkflow";

const fields: Array<[string, keyof Character]> = [
  ["名前", "name"],
  ["人物設定", "profile"],
  ["人物設定の詳細", "profileDetails"],
  ["Voice Design", "voiceDesign"],
  ["LoRA設定（adapter本体は別途必要）", "lora"],
  ["画像プロンプト", "imagePrompt"],
  ["画像プロンプト設定", "imagePromptPreferences"],
];
const shown = (value: unknown) => (typeof value === "string" ? value || "—" : value ? JSON.stringify(value, null, 2) : "—");
const fileName = (value: string) => value.split(/[\\/]/).pop() || value;

function IncomingMedia({ sessionId, item, asset }: { sessionId: string; item: CastImportItem; asset: "reference.wav" | "avatar-thumbnail.png" }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let owned = "";
    let cancelled = false;
    void apiFetch(`/api/casts/import/${encodeURIComponent(sessionId)}/media/${encodeURIComponent(item.key)}/${asset}`, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error();
        return response.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        owned = URL.createObjectURL(blob);
        setUrl(owned);
      })
      .catch(() => {
        if (!cancelled) setUrl("");
      });
    return () => {
      cancelled = true;
      if (owned) URL.revokeObjectURL(owned);
    };
  }, [asset, item.key, sessionId]);
  return asset === "reference.wav" ? <audio controls src={url || undefined} /> : url ? <img className="cast-compare-avatar" src={url} alt={`${item.incoming.name}の読み込み画像`} /> : <span>画像なし</span>;
}

// The comparison deliberately renders every optional field and navigation state in one shared dialog.
// eslint-disable-next-line complexity
export function CastImportDialog({ preparation, onClose, onApplied }: { preparation: CastImportPreparation; onClose: () => void; onApplied: (project: StudioProject, message: string, skipped: Array<{ path: string; reason: string }>) => void }) {
  const conflicts = useMemo(() => actionableCastImportConflicts(preparation), [preparation]);
  const [index, setIndex] = useState(0);
  const [decisions, setDecisions] = useState<Record<string, "overwrite" | "skip">>({});
  const [busy, setBusy] = useState(false);
  const item = conflicts[index];
  async function close() {
    try {
      await api.cancelCastImport(preparation.sessionId);
    } finally {
      onClose();
    }
  }
  async function apply() {
    setBusy(true);
    try {
      const result = await api.commitCastImport(
        preparation.sessionId,
        Object.entries(decisions).map(([incomingKey, action]) => ({ incomingKey, action })),
      );
      onApplied(result.project, castImportResultMessage(result.applied.length, result.skipped.length, preparation.errors.length, preparation.warnings), skippedCastImportReasons(preparation, result.skipped));
    } finally {
      setBusy(false);
    }
  }
  return (
    <ModalBackdrop onClose={() => void close()} disabled={busy}>
      <section className="modal cast-import-dialog" role="dialog" aria-modal="true" aria-label="キャストインポート">
        <DialogHeader eyebrow="CAST IMPORT" title={`重複キャストを確認 ${index + 1} / ${conflicts.length}`} description={item ? fileName(item.path) : undefined} />
        <CastImportWarnings warnings={preparation.warnings} />
        {item ? (
          <div className="cast-compare-grid">
            <h3>登録済み</h3>
            <h3>読み込み内容</h3>
            {fields.map(([label, key]) => {
              const changed = shown(item.existing?.[key]) !== shown(item.incoming[key]);
              return (
                <div className="cast-compare-row" key={key}>
                  <div className={changed ? "is-changed" : ""}>
                    <b>{label}</b>
                    <pre>{shown(item.existing?.[key])}</pre>
                  </div>
                  <div className={changed ? "is-changed" : ""}>
                    <b>{label}</b>
                    <pre>{shown(item.incoming[key])}</pre>
                  </div>
                </div>
              );
            })}
            <div className="cast-compare-row">
              <div className={item.existing?.audioHash !== item.incoming.audioHash ? "is-changed" : ""}>
                <b>参照WAV</b>
                <audio controls src={item.existing?.referenceAudioUrl} />
              </div>
              <div className={item.existing?.audioHash !== item.incoming.audioHash ? "is-changed" : ""}>
                <b>参照WAV</b>
                <IncomingMedia sessionId={preparation.sessionId} item={item} asset="reference.wav" />
              </div>
            </div>
            <div className="cast-compare-row">
              <div>
                <b>画像</b>
                {item.existing?.avatarThumbnailUrl ? <img className="cast-compare-avatar" src={item.existing.avatarThumbnailUrl} alt={`${item.existing.name}の登録画像`} /> : <span>画像なし</span>}
              </div>
              <div>
                <b>画像</b>
                <IncomingMedia sessionId={preparation.sessionId} item={item} asset="avatar-thumbnail.png" />
              </div>
            </div>
          </div>
        ) : (
          <div className="cast-exchange-results">
            {preparation.items.map((value) => (
              <p key={value.key}>
                {value.status === "new" ? "＋" : "＝"} {value.incoming.name}: {value.status === "new" ? "新規" : "同一内容のためスキップ"}
              </p>
            ))}
            {preparation.errors.map((error) => (
              <p key={error.path}>
                × {error.path}: {error.error}
              </p>
            ))}
          </div>
        )}
        {item && (
          <div className="cast-conflict-actions">
            <button type="button" className={decisions[item.key] === "skip" ? "active" : "secondary"} onClick={() => setDecisions((current) => ({ ...current, [item.key]: "skip" }))}>
              スキップ
            </button>
            <button type="button" className={decisions[item.key] === "overwrite" ? "active" : "secondary"} onClick={() => setDecisions((current) => ({ ...current, [item.key]: "overwrite" }))}>
              上書き
            </button>
          </div>
        )}
        <DialogFooter leading={item ? <span>{decisions[item.key] ? "判断済み" : "未決定"}</span> : undefined}>
          <button type="button" className="secondary" disabled={busy} onClick={() => void close()}>
            キャンセル
          </button>
          {item && index > 0 && (
            <button type="button" className="secondary" onClick={() => setIndex(index - 1)}>
              前へ
            </button>
          )}
          {item && index < conflicts.length - 1 && (
            <button type="button" disabled={!decisions[item.key]} onClick={() => setIndex(index + 1)}>
              次へ
            </button>
          )}
          {(!item || index === conflicts.length - 1) && (
            <button type="button" disabled={busy || conflicts.some((value) => !decisions[value.key])} onClick={() => void apply()}>
              まとめて適用
            </button>
          )}
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}

export function CastImportSkippedDialog({ skipped, onClose }: { skipped: Array<{ path: string; reason: string }>; onClose: () => void }) {
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal cast-exchange-dialog" role="dialog" aria-modal="true" aria-label="スキップしたキャスト">
        <DialogHeader eyebrow="CAST IMPORT" title="スキップしたキャスト" description="次のファイルは取り込みませんでした。" />
        <div className="cast-import-skipped-list">
          {skipped.map((item, index) => (
            <div key={`${item.path}-${index}`}>
              <b>{fileName(item.path)}</b>
              <span>{item.reason}</span>
            </div>
          ))}
        </div>
        <DialogFooter>
          <button type="button" onClick={onClose}>
            閉じる
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}

function CastImportWarnings({ warnings }: { warnings?: string[] }) {
  return (
    <>
      {warnings?.map((warning) => (
        <p role="alert" className="warning-box" key={warning}>
          {warning}
        </p>
      ))}
    </>
  );
}
