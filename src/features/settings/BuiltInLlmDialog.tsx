import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { formatDownloadSpeed, formatModelBytes, HfFilterKind, visibleModelTags } from "./huggingFaceModelUi";
import { isWindows } from "../shared/platform";
import { additionFinished } from "./modelAddition";
import { HfModelSearch } from "./HfModelSearch";
import { useBuiltInLlmDialogModel, type Download } from "./useBuiltInLlmDialogModel";

const tagLabels: Record<HfFilterKind, string> = {
  publisher: "提供元",
  family: "ファミリー",
  parameters: "規模",
  quantization: "量子化",
  purpose: "用途",
  role: "モデル役割",
  compatibility: "SCENA互換性",
};
function DownloadStatus({ status, speed }: { status: Download; speed: number }) {
  const known = status.totalBytes > 0;
  const percent = known ? Math.min(100, (status.downloadedBytes / status.totalBytes) * 100) : 0;
  const cancelling = status.state === "cancelling";
  return (
    <section className="hf-download-status" aria-label="モデル取得状況">
      <div>
        <strong>{cancelling ? "取り消しています…" : status.state === "complete" ? "モデル取得済み" : "モデルを取得しています…"}</strong>
        {known && <b>{Math.round(percent)}%</b>}
      </div>
      <span className={`progress-bar${known ? " determinate" : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.round(percent) : undefined}>
        <i style={known ? { width: `${percent}%` } : undefined} />
      </span>
      <div className="hf-download-metrics">
        <span>
          {formatModelBytes(status.downloadedBytes)} / {known ? formatModelBytes(status.totalBytes) : "計算中"}
        </span>
        {status.state !== "complete" && <span>{formatDownloadSpeed(speed)}</span>}
      </div>
      {status.currentFile && <small title={status.currentFile}>{status.currentFile}</small>}
      {status.preparation && (
        <p role="status">
          {status.preparation.message}
          {status.preparation.totalBytes > 0 && ` · 実行基盤 ${formatModelBytes(status.preparation.downloadedBytes)} / ${formatModelBytes(status.preparation.totalBytes)}`}
        </p>
      )}
      {status.preparation?.errorCategory && <small>分類: {status.preparation.errorCategory}</small>}
    </section>
  );
}

function HfAdditionAction({ status, starting, selected, needsToken, token, onDownload, onCancel }: { status: Download | null; starting: boolean; selected: string; needsToken: boolean; token: string; onDownload: () => void; onCancel: () => void }) {
  const active = !!status && !additionFinished(status);
  const cancelling = status?.state === "cancelling";
  if (status && additionFinished(status)) return null;
  return (
    <button type="button" className="primary" disabled={cancelling || starting || (!status && (!selected || (needsToken && !token.trim())))} onClick={active ? onCancel : onDownload}>
      {cancelling ? "取消要求中…" : active ? "追加を取り消す" : "取得して追加"}
    </button>
  );
}

function BuiltInFooter({
  route,
  busy,
  startingDownload,
  status,
  speed,
  selected,
  needsToken,
  token,
  onBack,
  onClose,
  onDownload,
  onRegister,
  onCancel,
}: {
  route: "start" | "hf" | "local";
  busy: boolean;
  startingDownload: boolean;
  status: Download | null;
  speed: number;
  selected: string;
  needsToken: boolean;
  token: string;
  onBack: () => void;
  onClose: () => void;
  onDownload: () => void;
  onRegister: () => void;
  onCancel: () => void;
}) {
  return (
    <DialogFooter className={`llm-route-footer is-${route}${startingDownload || status ? " download-dialog-footer" : ""}`}>
      {startingDownload && !status && (
        <section className="hf-download-status" aria-label="モデル取得状況">
          <div>
            <strong>取得を準備しています…</strong>
          </div>
          <span className="progress-bar" role="progressbar">
            <i />
          </span>
        </section>
      )}
      {status && <DownloadStatus status={status} speed={speed} />}
      <span className="dialog-footer-actions">
        {route !== "start" && (
          <button type="button" className="secondary" disabled={busy} onClick={onBack}>
            戻る
          </button>
        )}
        <button type="button" className="secondary" disabled={busy} onClick={onClose}>
          {status && additionFinished(status) ? "閉じる" : "キャンセル"}
        </button>
        {route === "hf" && <HfAdditionAction status={status} starting={startingDownload} selected={selected} needsToken={needsToken} token={token} onDownload={onDownload} onCancel={onCancel} />}
        {route === "local" && (
          <button type="button" className="primary" disabled={!selected} onClick={onRegister}>
            このモデルを登録
          </button>
        )}
      </span>
    </DialogFooter>
  );
}

type DialogModel = ReturnType<typeof useBuiltInLlmDialogModel>;

function BuiltInRouteBody({ model: m }: { model: DialogModel }) {
  if (m.route === "start") {
    return (
      <div className="llm-route-cards">
        <button type="button" onClick={() => m.setRoute("hf")}>
          <strong>Hugging Faceから探す</strong>
          <span>対応するモデルを検索して取得</span>
        </button>
        <button
          type="button"
          onClick={() => {
            m.setRoute("local");
            void m.local.choose();
          }}
        >
          <strong>{isWindows() ? "PC" : "Mac"}内のフォルダから選ぶ</strong>
          <span>元ファイルは移動・複製しません</span>
        </button>
      </div>
    );
  }
  return (
    <div className="dialog-form-fields">
      {m.route === "hf" && (
        <HfModelSearch
          query={m.search.query}
          onQuery={m.search.setQuery}
          onSearch={(event) => void m.search.search(event, new Set(), true)}
          busy={m.busy}
          hasModels={!!m.search.models.length}
          models={m.search.visible}
          selected={m.search.selected}
          onSelect={(repoId) => {
            m.search.setSelected(repoId);
            m.download.setNeedsToken(false);
          }}
          variants={m.download.variants}
          selectedVariant={m.download.selectedVariant}
          onVariant={m.download.selectVariant}
          message={m.download.message}
          filters={{
            tags: m.search.tagGroups,
            labels: tagLabels,
            selected: m.search.tags,
            capacity: m.search.maxSizeGb,
            disabled: m.busy,
            order: m.search.order,
            onOrder: (order) => void m.search.search(undefined, m.search.tags, false, order),
            onTag: m.search.toggleTag,
            onCapacity: m.search.setMaxSizeGb,
            onClear: () => {
              m.search.setMaxSizeGb(null);
              m.search.setOrder(null);
              m.search.queue(new Set(), null);
            },
          }}
        />
      )}
      {m.route === "local" && (
        <>
          <button type="button" className="secondary" onClick={() => void m.local.choose()}>
            別のフォルダを選ぶ
          </button>
          <div className="llm-choice-list hf-choice-list" role="radiogroup" aria-label="モデル">
            {m.local.models.map((item) => (
              <label key={item.id}>
                <input type="radio" name="built-in-model" checked={m.local.selected === item.id} onChange={() => m.local.setSelected(item.id)} />
                <span className="hf-choice-main">
                  <strong>{item.displayName}</strong>
                  <span>
                    {visibleModelTags(item.inferredTags).map((tag) => (
                      <small key={tag.kind + ":" + tag.value}>{tag.value}</small>
                    ))}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </>
      )}
      {m.download.needsToken && (
        <label className="dialog-form-field">
          Hugging Face認証
          <input type="password" autoComplete="off" value={m.download.token} onChange={(event) => m.download.setToken(event.target.value)} />
          <small>このモデルにはread tokenが必要です。Keychainへ保存します。アクセス同意はHugging Faceのブラウザ画面で行ってください。</small>
        </label>
      )}
      {m.search.completed && (
        <p className="subtle" role="status">
          {m.search.visible.length}件見つかりました。
        </p>
      )}
      {m.search.message && (
        <p className="subtle" role="status">
          {m.search.message}
        </p>
      )}
    </div>
  );
}

export function BuiltInLlmDialog({ onClose, onAdded }: { onClose: () => void; onAdded: (name: string) => Promise<void> }) {
  const m = useBuiltInLlmDialogModel(onAdded);
  const selected = m.route === "hf" ? m.search.selected : m.local.selected;
  return (
    <ModalBackdrop onClose={onClose} disabled={m.busy}>
      <section className="modal llm-setting-dialog" role="dialog" aria-modal="true" aria-labelledby="built-in-title">
        <DialogHeader title="SCENA内蔵LLMにモデルを追加" titleId="built-in-title" />
        <BuiltInRouteBody model={m} />
        <BuiltInFooter
          key={m.route}
          route={m.route}
          busy={m.busy}
          startingDownload={m.download.starting}
          status={m.download.status}
          speed={m.download.speed}
          selected={isWindows() && m.route === "hf" && !m.download.selectedVariant ? "" : selected}
          needsToken={m.download.needsToken}
          token={m.download.token}
          onBack={() => {
            m.setRoute("start");
            m.search.setSelected("");
            m.local.setSelected("");
          }}
          onClose={onClose}
          onDownload={() => void m.download.download()}
          onRegister={() => void m.local.register()}
          onCancel={() => void m.download.cancel()}
        />
      </section>
    </ModalBackdrop>
  );
}
