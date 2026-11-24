/* eslint-disable complexity, react-hooks/set-state-in-effect -- This compact dialog maps backend job states and publishes catalogue data only after awaited API boundaries. */
import { useCallback, useEffect, useState } from "react";
import metadata from "../../../release-metadata.json";
import { api } from "../../api";
import type { TtsCatalog, TtsRegistry } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { recommendedTtsModel, useTtsInstallJob } from "../settings/useTtsInstallJob";
import { LlmModelHintDialog } from "../settings/LlmModelHintDialog";
import { installationIdentity } from "../../installationIdentity";

export const FIRST_RUN_SETUP_KEY = `irodori-scena:first-run-setup:${metadata.version}`;
export const FIRST_RUN_INSTALLATION_KEY = "irodori-scena:first-run-installation";

function initialOpen(): boolean {
  const current = installationIdentity();
  if (current === null) return window.localStorage.getItem(FIRST_RUN_SETUP_KEY) !== "seen";
  const previous = window.localStorage.getItem(FIRST_RUN_INSTALLATION_KEY);
  if (previous !== null) return previous !== current;
  // Migrate users who dismissed the version-based guide before install
  // identities existed. An update keeps the installer marker, while a later
  // uninstall/reinstall changes it and opens the guide again.
  if (window.localStorage.getItem(FIRST_RUN_SETUP_KEY) === "seen") {
    window.localStorage.setItem(FIRST_RUN_INSTALLATION_KEY, current);
    return false;
  }
  return true;
}

export function FirstRunSetupDialog({ onOpenLlmSettings }: { onOpenLlmSettings: () => void }) {
  const [open, setOpen] = useState(initialOpen);
  const [catalog, setCatalog] = useState<TtsCatalog | null>(null);
  const [registry, setRegistry] = useState<TtsRegistry | null>(null);
  const [loadError, setLoadError] = useState("");
  const [hintOpen, setHintOpen] = useState(false);
  const refresh = useCallback(async () => {
    const [nextCatalog, nextRegistry] = await Promise.all([api.ttsCatalog(), api.ttsRegistry()]);
    setCatalog(nextCatalog);
    setRegistry(nextRegistry);
  }, []);
  const install = useTtsInstallJob(refresh);
  useEffect(() => {
    if (open) void refresh().catch((reason) => setLoadError((reason as Error).message));
  }, [open, refresh]);
  if (!open) return null;
  const recommended = recommendedTtsModel(catalog?.models ?? []);
  const installed = !!recommended && !!registry?.models.some((item) => item.id === recommended.id);
  const recommendedVariant = recommended?.variants?.filter((variant) => variant.available).sort((a, b) => a.recommendedOrder - b.recommendedOrder)[0];
  const progress = install.job?.totalBytes ? Math.min(100, (install.job.downloadedBytes / install.job.totalBytes) * 100) : 0;
  const close = () => {
    window.localStorage.setItem(FIRST_RUN_SETUP_KEY, "seen");
    const current = installationIdentity();
    if (current !== null) window.localStorage.setItem(FIRST_RUN_INSTALLATION_KEY, current);
    setOpen(false);
  };
  const openLlm = () => {
    close();
    onOpenLlmSettings();
  };
  return (
    <ModalBackdrop onClose={close}>
      <section className="modal first-run-setup-dialog" role="dialog" aria-modal="true" aria-labelledby="first-run-setup-title">
        <DialogHeader eyebrow="GETTING STARTED" title="生成機能の準備" titleId="first-run-setup-title" description="音声合成にはIrodori-TTS、AI機能にはLLMの準備が必要です。必要なものをここから用意できます。" />
        <div className="first-run-setup-content">
          <section className="surface-soft first-run-setup-section" aria-labelledby="first-run-tts-title">
            <h3 id="first-run-tts-title">音声合成（Irodori-TTS）</h3>
            {!catalog && !loadError && (
              <p className="subtle" role="status">
                検証済みモデルを確認しています…
              </p>
            )}
            {recommended && (
              <p>
                <strong>{recommended.displayName}</strong> は、このSCENA版で検証済みの推奨モデルです。エンジン、Python環境、Codec、tokenizerもまとめて導入します。
              </p>
            )}
            {!recommended && catalog && <p className="warning-text">現在導入できる推奨モデルがありません。</p>}
            {loadError && (
              <p className="warning-text" role="alert">
                モデル情報を読み込めませんでした: {loadError}
              </p>
            )}
            {installed ? (
              <p className="first-run-ready" role="status">
                導入済みです。音声を生成できます。
              </p>
            ) : (
              recommended &&
              !install.active &&
              install.job?.state !== "complete" && (
                <button type="button" className="primary" onClick={() => void (recommendedVariant ? install.startVariant(recommended.id, recommendedVariant.id) : install.start(recommended))}>
                  {install.job?.state === "failed" || install.job?.state === "cancelled" ? "ダウンロードを再試行" : "推奨モデルをダウンロード"}
                </button>
              )
            )}
          </section>
          <section className="surface-soft first-run-setup-section" aria-labelledby="first-run-llm-title">
            <div className="first-run-section-heading">
              <h3 id="first-run-llm-title">AI機能（LLM）</h3>
              <button type="button" className="quiet-button llm-hint-link" onClick={() => setHintOpen(true)}>
                使い方のヒント
              </button>
            </div>
            <p>AI台本などを使うにはLLMが必要です。ローカルで使う場合はモデルを取得し、外部のLLMを使う場合は接続先を設定してください。</p>
            <button type="button" className="button-ai" onClick={openLlm}>
              LLM設定を開く
            </button>
          </section>
        </div>
        {(install.error || install.job?.error) && (
          <p className="warning-text" role="alert">
            {install.job?.error ?? install.error}
          </p>
        )}
        <DialogFooter className={install.job ? "download-dialog-footer" : ""}>
          {install.job && (
            <div className="tts-install-progress" role="status">
              <b>{install.job.state === "complete" ? "導入が完了しました" : install.job.state === "failed" ? "導入に失敗しました" : install.job.state === "cancelled" ? "導入を取り消しました" : install.job.state === "cancelling" ? "取消中です" : "必要な資産を導入中"}</b>
              <span>{install.job.currentFile ?? install.job.stage}</span>
              <div className="progress-bar determinate">
                <i style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}
          <span className="dialog-footer-actions">
            {install.job && ["queued", "running"].includes(install.job.state) && (
              <button type="button" className="danger" onClick={() => void install.cancel()}>
                取消
              </button>
            )}
            <button type="button" className="secondary" onClick={close}>
              {install.job?.state === "complete" ? "閉じる" : "あとで"}
            </button>
          </span>
        </DialogFooter>
      </section>
      {hintOpen && <LlmModelHintDialog onClose={() => setHintOpen(false)} />}
    </ModalBackdrop>
  );
}
