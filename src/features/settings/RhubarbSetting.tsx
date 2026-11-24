import { useCallback, useEffect, useRef, useState } from "react";
import { api, openExternal } from "../../api";
import { ApiConnectionError, ApiError } from "../../api-error";
import type { RhubarbStatus } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { formatModelBytes } from "./huggingFaceModelUi";
import { ModelBoardCardFooter } from "./ModelBoardCardFooter";
import { useSequentialPolling } from "../shared/useSequentialPolling";

function formatAddonSize(bytes?: number | null) {
  if (bytes == null) return "容量未取得";
  if (bytes < 1024 ** 3) return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function RhubarbDescription({ status }: { status: RhubarbStatus }) {
  return (
    <div className="dialog-form-fields">
      <p>
        {status.updateAvailable
          ? `口パクLAB用アドオンの更新があります。ダウンロードサイズは${formatAddonSize(status.archiveBytes)}です。更新後は古い版を削除します。`
          : status.ready
            ? `Rhubarb ${status.version}（${status.license}）はこの端末で使用できます。`
            : `口パクLAB生成に必要なRhubarb ${status.version}（${status.license}）を追加します。ダウンロードサイズは${formatAddonSize(status.archiveBytes)}です。`}
      </p>
      {status.japaneseAddon && <p>日本語の口形補正（{status.japaneseAddon.license}）を含みます。</p>}
      <button type="button" className="quiet-button" onClick={() => void openExternal(status.sourceUrl)}>
        ソースとライセンスを確認
      </button>
      {!status.supported && <p className="warning-text">このOSまたはCPUには対応していません。</p>}
      {status.supported && !status.available && <p className="warning-text">このプラットフォーム向けアドオンはまだ公開されていません。</p>}
    </div>
  );
}

function RhubarbProgress({ status }: { status: RhubarbStatus }) {
  const job = status.job ?? { state: "queued", message: "Rhubarbの追加を準備しています…", totalBytes: status.archiveBytes, downloadedBytes: 0 };
  const total = job.totalBytes ?? status.archiveBytes;
  const downloaded = job.downloadedBytes ?? 0;
  const known = job.state === "downloading" && total > 0;
  const percent = known ? Math.min(100, (downloaded / total) * 100) : 0;
  return (
    <section className="hf-download-status" aria-label="Rhubarb取得状況">
      <div role="status">
        <strong>{job.message}</strong>
        {known && <b>{Math.round(percent)}%</b>}
      </div>
      <span className={`progress-bar${known ? " determinate" : ""}`} role="progressbar" aria-label="Rhubarb取得状況" aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.round(percent) : undefined}>
        <i style={known ? { width: `${percent}%` } : undefined} />
      </span>
      {job.state === "downloading" && (
        <small>
          {formatModelBytes(downloaded)} / {total > 0 ? formatModelBytes(total) : "容量未取得"}
        </small>
      )}
    </section>
  );
}

function canRemove(status: RhubarbStatus, exportMode: boolean, startupMode: boolean) {
  return status.installed && !exportMode && !startupMode;
}

function needsInstall(status: RhubarbStatus) {
  return !status.ready || status.updateAvailable;
}

function installFinished(status: RhubarbStatus) {
  return !status.job || ["complete", "failed", "cancelled"].includes(status.job.state);
}

function updateSucceeded(status: RhubarbStatus) {
  return status.ready && !status.updateAvailable && (!status.job || status.job.state === "complete");
}

function dialogTitle(status: RhubarbStatus, exportMode: boolean, startupMode: boolean) {
  if (startupMode) return "口パクLAB用アドオンを更新";
  if (!exportMode) return "Rhubarb";
  return status.updateAvailable ? "口パクLAB用アドオンを更新" : "口パクLABにRhubarbを追加";
}

function installLabel(status: RhubarbStatus, exportMode: boolean) {
  if (status.updateAvailable) return exportMode ? "更新してエクスポート" : "更新する";
  return exportMode ? "追加してエクスポート" : "Rhubarbを追加";
}

function cancelLabel(working: boolean, cancelRequested: boolean, startupMode: boolean) {
  if (working) return cancelRequested ? "キャンセル中…" : "キャンセル";
  return startupMode ? "後で" : "キャンセル";
}

function settingLabel(status: RhubarbStatus | null) {
  if (!status) return "確認中";
  if (status.updateAvailable) return "更新があります";
  if (status.ready) return "使用可能";
  return status.available ? "未導入" : "配布準備中";
}

function retryableStatusFailure(error: unknown) {
  return error instanceof ApiConnectionError || (error instanceof ApiError && ([408, 429].includes(error.status) || (error.status >= 500 && error.status < 600)));
}

export function RhubarbDialog({ status, exportMode = false, startupMode = false, onClose, onReady, onChanged }: { status: RhubarbStatus; exportMode?: boolean; startupMode?: boolean; onClose: () => void; onReady?: () => void; onChanged: (status: RhubarbStatus) => void }) {
  const [working, setWorking] = useState(() => !installFinished(status));
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const acceptStatus = useCallback(
    (next: RhubarbStatus) => {
      onChanged(next);
      if (updateSucceeded(next)) onReady?.();
    },
    [onChanged, onReady],
  );
  useSequentialPolling({
    enabled: working && !starting,
    intervalMs: 500,
    initialDelayMs: 500,
    poll: api.rhubarbStatus,
    terminal: (next) => installFinished(next),
    onResult: (next) => {
      acceptStatus(next);
      setError(next.job?.error ?? "");
      if (installFinished(next)) {
        setWorking(false);
      }
    },
    errorPolicy: (reason) => (retryableStatusFailure(reason) ? "retry" : "stop"),
    onError: (reason) => {
      if (!retryableStatusFailure(reason)) setWorking(false);
      setError((reason as Error).message);
    },
  });
  const install = async () => {
    setError("");
    setStarting(true);
    try {
      setWorking(true);
      const job = await api.installRhubarb();
      if (mounted.current) onChanged({ ...status, job });
    } catch (reason) {
      if (!mounted.current) return;
      setWorking(false);
      setError((reason as Error).message);
    } finally {
      if (mounted.current) setStarting(false);
    }
  };
  const remove = async () => {
    if (!window.confirm("Rhubarb本体と解析キャッシュを削除します。エクスポート済みのWAV・LABは削除されません。")) return;
    try {
      const next = await api.deleteRhubarb();
      if (mounted.current) onChanged(next);
    } catch (reason) {
      if (mounted.current) setError((reason as Error).message);
    }
  };
  const cancel = async () => {
    try {
      await api.cancelRhubarbInstall();
    } catch (reason) {
      if (mounted.current) setError((reason as Error).message);
    }
  };
  return (
    <ModalBackdrop onClose={working ? () => {} : onClose} disabled={working}>
      <section className="modal llm-setting-dialog" role="dialog" aria-modal="true" aria-labelledby="rhubarb-dialog-title">
        <DialogHeader eyebrow="LIP SYNC" title={dialogTitle(status, exportMode, startupMode)} titleId="rhubarb-dialog-title" description="実音声からPSDToolKit互換の口形LABを生成します。" />
        <RhubarbDescription status={status} />
        <div className="dialog-form-fields">
          {working && <RhubarbProgress status={status} />}
          {error && (
            <p className="warning-text" role="alert">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          {canRemove(status, exportMode, startupMode) && (
            <button type="button" className="danger" disabled={working} onClick={() => void remove()}>
              削除
            </button>
          )}
          <button type="button" className="secondary" disabled={starting || (working && !!status.job?.cancelRequested)} onClick={working ? () => void cancel() : onClose}>
            {cancelLabel(working, !!status.job?.cancelRequested, startupMode)}
          </button>
          {needsInstall(status) && (
            <button type="button" className="primary" disabled={working || !status.available} onClick={() => void install()}>
              {installLabel(status, exportMode)}
            </button>
          )}
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}

export function RhubarbSetting() {
  const [status, setStatus] = useState<RhubarbStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const retryStatus = () => {
    setLoadError(false);
    void api
      .rhubarbStatus()
      .then(setStatus)
      .catch(() => setLoadError(true));
  };
  useEffect(() => {
    void api
      .rhubarbStatus()
      .then(setStatus)
      .catch(() => setLoadError(true));
  }, []);
  const stateLabel = settingLabel(status);
  return (
    <>
      <div className="settings-panel-intro">
        <h2 id="rhubarb-settings-heading" tabIndex={-1}>
          LAB設定
        </h2>
        <p className="subtle">実音声からPSDToolKit互換の口形LABを生成するライブラリを管理します。</p>
        {loadError && (
          <p className="warning-text" role="alert">
            Rhubarbの状態を確認できませんでした。
            <button type="button" className="settings-title-action" onClick={retryStatus}>
              再試行
            </button>
          </p>
        )}
      </div>
      <div className="model-selection-control">
        <button type="button" className={`model-selection-trigger model-board-card${status?.ready ? " is-default" : ""}`} onClick={() => setOpen(true)} disabled={!status}>
          <span className="model-card-heading">
            <strong>Rhubarb</strong>
          </span>
          <span className="model-card-body llm-card-meta">
            <span className="model-card-tag is-neutral">口パクLAB</span>
          </span>
          <span className="subtle">{stateLabel}</span>
          <ModelBoardCardFooter isDefault={false} badge={status?.ready ? "導入済み" : undefined} metadata={status ? `v${status.version} · ${formatAddonSize(status.archiveBytes)}` : "確認中"} />
        </button>
        <button type="button" className="model-selection-details" aria-label="Rhubarbの詳細" disabled={!status} onClick={() => setOpen(true)}>
          詳細
        </button>
      </div>
      {open && status && <RhubarbDialog status={status} onClose={() => setOpen(false)} onChanged={setStatus} />}
    </>
  );
}
