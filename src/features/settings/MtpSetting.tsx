import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import type { LlmCard } from "../../types";
import { useSequentialPolling } from "../shared/useSequentialPolling";

function mtpProgressLabel(active: boolean, progress: [number, number]) {
  return active && progress[1] > 0 ? `・${Math.min(100, Math.round((progress[0] / progress[1]) * 100))}%` : "";
}

function MtpProgress({ active, progress }: { active: boolean; progress: [number, number] }) {
  if (!active) return null;
  const known = progress[1] > 0;
  const percent = known ? Math.min(100, (progress[0] / progress[1]) * 100) : 0;
  return (
    <span className={`progress-bar${known ? " determinate" : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.round(percent) : undefined}>
      <i style={known ? { width: `${percent}%` } : undefined} />
    </span>
  );
}

export function MtpSetting({ card, settings, setSettings }: { card: LlmCard; settings: LlmCard["settings"]; setSettings: (settings: LlmCard["settings"]) => void }) {
  const [installed, setInstalled] = useState(card.mtp?.draftInstalled ?? false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [diskBytes, setDiskBytes] = useState(0);
  const [progress, setProgress] = useState<[number, number]>([0, 0]);
  const applyAsset = useCallback((asset: Awaited<ReturnType<typeof api.mtpAsset>>) => {
    setInstalled(asset.installed);
    setJobId(asset.download?.id ?? null);
    setDiskBytes(asset.diskBytes);
    setProgress([asset.download?.downloadedBytes ?? 0, asset.download?.totalBytes ?? 0]);
  }, []);
  useEffect(() => {
    if (!card.mtp?.supported) return;
    void api.mtpAsset().then(applyAsset);
  }, [applyAsset, card.mtp?.supported]);
  useSequentialPolling({ enabled: !!jobId, intervalMs: 1000, initialDelayMs: 1000, poll: api.mtpAsset, onResult: applyAsset });
  if (!card.mtp?.supported) return null;
  return (
    <div className="llm-mtp-setting">
      <p className="subtle">
        MTP用assistant: {installed ? "取得済み" : jobId ? "ダウンロード中" : "未取得"}
        {diskBytes > 0 ? `・${(diskBytes / 1024 ** 3).toFixed(2)} GiB` : ""}
        {mtpProgressLabel(Boolean(jobId), progress)}
      </p>
      <MtpProgress active={Boolean(jobId)} progress={progress} />
      {!installed && !jobId && (
        <button type="button" className="secondary settings-inline-action" onClick={() => void api.downloadMtpAsset().then((job) => setJobId(job.id))}>
          MTP用モデルをダウンロード
        </button>
      )}
      {jobId && (
        <button type="button" className="secondary settings-inline-action" onClick={() => void api.cancelMtpAsset(jobId).then(() => setJobId(null))}>
          MTPダウンロードを取消
        </button>
      )}
      <label className="checkbox-line">
        <input type="checkbox" disabled={!installed} checked={settings.mtp ?? false} onChange={(event) => setSettings({ ...settings, mtp: event.target.checked })} />
        MTPを有効にする
      </label>
    </div>
  );
}
