/* eslint-disable react-hooks/set-state-in-effect -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { useCallback, useEffect, useState } from "react";
import { api, chooseDirectory } from "../../api";
import type { TtsAssetCard, TtsCatalog, TtsCatalogItem, TtsCatalogVariant, TtsLibraryModelJob, TtsLibraryScan, TtsProjectSelection, TtsRegistry } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { modelRegistryCache } from "../shared/modelRegistryCache";
import { ModelMetadataTags, TtsCardContent } from "./TtsModelCardContent";
export { TtsCardContent } from "./TtsModelCardContent";
import { ModelSelectionPopover } from "./ModelSelectionPopover";
import { CapabilityList, formatSize, switchTtsModel, TtsModelDialog } from "./TtsModelDialog";
import { useTtsInstallJob } from "./useTtsInstallJob";
import { orderTtsVariantsForDisplay } from "./ttsVariantOrder";
import { useSequentialPolling } from "../shared/useSequentialPolling";
import { DoubleChevron } from "../shared/DoubleChevron";
import { MEANFLOW_MODEL_REPO } from "../shared/ttsSampling";
import { sortTtsModelCards } from "./modelCardOrder";
import { TtsModelOperationNotice } from "./TtsModelOperationNotice";

function LibraryScanChoices({ scan, enginePath, selected, active, onEngine, onSelect }: { scan: TtsLibraryScan; enginePath: string; selected: string; active: boolean; onEngine: (value: string) => void; onSelect: (value: string) => void }) {
  return (
    <>
      {scan.engines.length > 1 && (
        <label className="dialog-form-field">
          使用するエンジン
          <select value={enginePath} disabled={active} onChange={(event) => onEngine(event.target.value)}>
            <option value="">選択してください</option>
            {scan.engines.map((engine) => (
              <option key={engine.id} value={engine.path}>
                {engine.path}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="llm-choice-list hf-choice-list" role="radiogroup" aria-label="モデル">
        {scan.models.map((model) => (
          <label key={model.id}>
            <input type="radio" name="tts-library-model" disabled={!model.tokenizerPath || active} checked={selected === model.id} onChange={() => onSelect(model.id)} />
            <span className="hf-choice-main">
              <strong>{model.displayName}</strong>
              <span>
                <small>
                  {model.location}
                  {model.revision ? ` · ${model.revision.slice(0, 12)}` : ""}
                </small>
                <small>{model.tokenizerPath ? "tokenizer 検出済み" : "tokenizer不足"}</small>
              </span>
            </span>
          </label>
        ))}
      </div>
      {scan.warnings.map((warning, index) => (
        <p className="warning-text" key={`${warning.code}-${index}`}>
          {warning.message}
        </p>
      ))}
    </>
  );
}

function LibraryJobProgress({ job }: { job: TtsLibraryModelJob }) {
  const progress = job.totalBytes ? Math.min(100, (job.processedBytes / job.totalBytes) * 100) : 0;
  return (
    <div className="tts-install-progress" role="status">
      <b>{job.stage}</b>
      <span>{job.currentFile}</span>
      <div className="progress-bar determinate">
        <i style={{ width: `${progress}%` }} />
      </div>
    </div>
  );
}

function LibraryDialogFooter({ job, active, canRegister, onClose, onJob, onRegister }: { job: TtsLibraryModelJob | null; active: boolean; canRegister: boolean; onClose: () => void; onJob: (job: TtsLibraryModelJob) => void; onRegister: () => void }) {
  const activeJob = active ? job : null;
  return (
    <DialogFooter className={activeJob ? "download-dialog-footer" : ""}>
      {activeJob && <LibraryJobProgress job={activeJob} />}
      <span className="dialog-footer-actions">
        {activeJob && (
          <button type="button" className="secondary" onClick={() => void api.cancelTtsLibraryModelJob(activeJob.id).then(onJob)}>
            登録を取消
          </button>
        )}
        <button type="button" className="secondary" disabled={active} onClick={onClose}>
          キャンセル
        </button>
        <button type="button" className="primary" disabled={!canRegister} onClick={onRegister}>
          このモデルを登録
        </button>
      </span>
    </DialogFooter>
  );
}

function AddLibraryDialog({ onClose, onChanged }: { onClose: () => void; onChanged: () => Promise<void> }) {
  const [scan, setScan] = useState<TtsLibraryScan | null>(null);
  const [enginePath, setEnginePath] = useState("");
  const [selected, setSelected] = useState("");
  const [job, setJob] = useState<TtsLibraryModelJob | null>(null);
  const [message, setMessage] = useState("");
  const active = !!job && ["queued", "running", "cancelling"].includes(job.state);
  useSequentialPolling({
    enabled: active && !!job,
    intervalMs: 400,
    initialDelayMs: 400,
    poll: () => api.ttsLibraryModelJob(job!.id),
    terminal: (next) => !["queued", "running", "cancelling"].includes(next.state),
    onResult: async (next, signal) => {
      if (next.state === "complete") await onChanged();
      if (signal.aborted) return;
      setJob(next);
      setMessage("");
      if (next.state === "complete") onClose();
    },
    onError: (error) => setMessage((error as Error).message),
  });
  const choose = async () => {
    const path = await chooseDirectory("Irodori-TTSライブラリ接続先を選択");
    if (!path) return;
    try {
      const result = await api.scanTtsLibrary(path);
      setScan(result);
      setEnginePath(result.engines.length === 1 ? result.engines[0].path : "");
      setSelected("");
      setJob(null);
      setMessage(result.models.length ? "利用できるモデルを選んでください。" : "利用できるモデルが見つかりませんでした。");
    } catch (error) {
      setMessage(`フォルダを確認できませんでした: ${(error as Error).message}`);
    }
  };
  const register = async () => {
    const model = scan?.models.find((item) => item.id === selected);
    const codec = scan?.codecs[0];
    if (!scan || !model || !codec || !enginePath) return;
    try {
      const registry = await api.registerTtsLibrary(scan.root, enginePath, scan.displayName);
      const library = registry.libraries.find((item) => item.root === scan.root);
      if (!library) throw new Error("接続先を登録できませんでした。");
      setJob(await api.registerTtsLibraryModel(library.id, model.path, codec.path));
      setMessage("");
    } catch (error) {
      setMessage(`登録できませんでした: ${(error as Error).message}`);
    }
  };
  const canRegister = !!selected && !!enginePath && !!scan?.codecs.length && !active;
  return (
    <ModalBackdrop onClose={onClose} disabled={active}>
      <section className="modal llm-setting-dialog" role="dialog" aria-modal="true" aria-labelledby="tts-library-title">
        <DialogHeader title="ストレージから追加" titleId="tts-library-title" />
        <div className="dialog-form-fields">
          <button type="button" className="secondary" disabled={active} onClick={() => void choose()}>
            {scan ? "別のフォルダを選ぶ" : "フォルダを選ぶ"}
          </button>
          {scan && (
            <LibraryScanChoices
              scan={scan}
              enginePath={enginePath}
              selected={selected}
              active={active}
              onEngine={setEnginePath}
              onSelect={(value) => {
                setSelected(value);
                setJob(null);
              }}
            />
          )}
          {job?.error && <p className="warning-text">{job.error}</p>}
          {message && (
            <p className="subtle" role="status">
              {message}
            </p>
          )}
        </div>
        <LibraryDialogFooter job={job} active={active} canRegister={canRegister} onClose={onClose} onJob={setJob} onRegister={() => void register()} />
      </section>
    </ModalBackdrop>
  );
}

function CatalogCards({ items, registry, busy, onStart, onVariant, onChanged }: { items: TtsCatalogItem[]; registry: TtsRegistry | null; busy: boolean; onStart: (item: TtsCatalogItem) => void; onVariant: (modelId: string, variant: TtsCatalogVariant) => void; onChanged: () => Promise<void> }) {
  return (
    <div className="tts-catalog-list">
      {items.map((item) => (
        <CatalogCard key={item.id} item={item} card={registry?.models.find((card) => card.id === item.id)} busy={busy} onStart={onStart} onVariant={onVariant} onChanged={onChanged} />
      ))}
    </div>
  );
}

export function VariantPanel({ item, variants, installed, verified, busy, onVariant, onChanged }: { item: TtsCatalogItem; variants: TtsCatalogVariant[]; installed: Set<string>; verified: boolean; busy: boolean; onVariant: (modelId: string, variant: TtsCatalogVariant) => void; onChanged: () => Promise<void> }) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const activate = async (variant: TtsCatalogVariant) => {
    if (!installed.has(variant.id)) return onVariant(item.id, variant);
    if (confirming !== variant.id) return setConfirming(variant.id);
    await api.deleteTtsVariant(item.id, variant.id);
    setConfirming(null);
    await onChanged();
  };
  return (
    <div
      className="tts-variant-panel"
      onMouseLeave={() => setConfirming(null)}
      onKeyDown={(event) => {
        if (event.key === "Escape") setConfirming(null);
      }}
    >
      {variants.map((variant) => (
        <button
          key={variant.id}
          type="button"
          title={variant.available ? undefined : variant.unavailableReason}
          data-scena-tooltip={variant.available ? `ダウンロードサイズ：${formatSize(variant.sizeBytes)}` : undefined}
          className={`tts-variant-pill${verified && installed.has(variant.id) ? " is-installed" : ""}${confirming === variant.id ? " is-confirming" : ""}`}
          disabled={busy || !variant.available}
          onClick={() => void activate(variant)}
        >
          {confirming === variant.id ? `${variant.precision}を削除？` : variant.precision}
          {!variant.available && <small>{variant.unavailableReason}</small>}
        </button>
      ))}
      {variants.some((variant) => variant.backend === "mlx") && <p className="tts-variant-source-note">FP32はHugging FaceのAratakoから、FP16・8bitはmlx-communityからダウンロードします。</p>}
    </div>
  );
}

type CatalogCardActionProps = {
  item: TtsCatalogItem;
  card?: TtsAssetCard;
  recommended?: TtsCatalogVariant;
  installed: Set<string>;
  busy: boolean;
  onStart: (item: TtsCatalogItem) => void;
  onVariant: (modelId: string, variant: TtsCatalogVariant) => void;
};

export function CatalogCardAction({ item, card, recommended, installed, busy, onStart, onVariant }: CatalogCardActionProps) {
  const present = recommended ? installed.has(recommended.id) : Boolean(card);
  const install = () => (recommended ? onVariant(item.id, recommended) : onStart(item));
  const download = recommended ?? item;
  return (
    <span className="tts-catalog-action" data-scena-tooltip={`ダウンロードサイズ：${formatSize(download.sizeBytes)}`}>
      <button type="button" className="primary" disabled={present || busy || !item.installable} onClick={install}>
        {present ? "導入済み" : "追加"}
      </button>
      <span className="tts-model-format">
        <span>{formatSize(download.sizeBytes).replace(" GB", "GB")}</span>
        <span>[{download.precision}]</span>
      </span>
    </span>
  );
}

function VariantToggle({ item, expanded, onToggle }: { item: TtsCatalogItem; expanded: boolean; onToggle: () => void }) {
  return (
    <button type="button" className="tts-variant-toggle" aria-expanded={expanded} aria-label={`${item.displayName}のバリアントを${expanded ? "閉じる" : "開く"}`} onClick={onToggle}>
      <DoubleChevron className="tts-variant-chevron" />
    </button>
  );
}

function CatalogCard({ item, card, busy, onStart, onVariant, onChanged }: { item: TtsCatalogItem; card?: TtsAssetCard; busy: boolean; onStart: (item: TtsCatalogItem) => void; onVariant: (modelId: string, variant: TtsCatalogVariant) => void; onChanged: () => Promise<void> }) {
  const [expanded, setExpanded] = useState(false);
  const variants = orderTtsVariantsForDisplay((item.variants ?? []).filter((variant) => variant.visible !== false && !variant.derivedLocal));
  const recommended = [...variants].filter((variant) => variant.available).sort((a, b) => a.recommendedOrder - b.recommendedOrder)[0];
  const legacyInstalled = card ? ["pytorch-fp32"] : [];
  const installed = new Set(card?.installedVariants?.map((variant) => variant.id) ?? legacyInstalled);
  return (
    <article className={`tts-catalog-card${expanded ? " is-expanded" : ""}`}>
      <span>
        <span className="tts-model-title">
          <strong>{item.displayName}</strong>
        </span>
        <small>
          {item.generation} · revision {item.revision?.slice(0, 12)}
        </small>
        {item.description && <span className="tts-model-description">{item.description}</span>}
      </span>
      <ModelMetadataTags card={item} />
      {item.legacy && (
        <span className="tts-card-badges">
          <i>レガシー</i>
        </span>
      )}
      <CapabilityList item={item} />
      {item.notice && <p className="tts-model-notice">{item.notice}</p>}
      <CatalogCardAction item={item} card={card} recommended={recommended} installed={installed} busy={busy} onStart={onStart} onVariant={onVariant} />
      {variants.length > 0 && <VariantToggle item={item} expanded={expanded} onToggle={() => setExpanded((value) => !value)} />}
      {expanded && <VariantPanel item={item} variants={variants} installed={installed} verified={card?.verification === "verified"} busy={busy} onVariant={onVariant} onChanged={onChanged} />}
    </article>
  );
}

function AddModelDialog({ catalog, registry, onClose, onInstalled, onChanged }: { catalog: TtsCatalog; registry: TtsRegistry | null; onClose: () => void; onInstalled: () => Promise<void>; onChanged: () => Promise<void> }) {
  const { job, error, active: busy, start, startVariant, cancel } = useTtsInstallJob(onInstalled);
  const sort = (items: TtsCatalogItem[]) => items.sort((a, b) => (a.recommendedOrder ?? 99) - (b.recommendedOrder ?? 99));
  const isOtherModel = (item: TtsCatalogItem) => item.legacy || item.repo === MEANFLOW_MODEL_REPO;
  const progress = job?.totalBytes ? Math.min(100, (job.downloadedBytes / job.totalBytes) * 100) : 0;
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal tts-add-dialog" role="dialog" aria-modal="true">
        <DialogHeader title="音声モデルを追加" description="下記から使用する音声モデルを1つ選んでダウンロードしてください。" />
        <CatalogCards items={sort(catalog.models.filter((item) => !isOtherModel(item)))} registry={registry} busy={busy} onStart={(item) => void start(item)} onVariant={(modelId, variant) => void startVariant(modelId, variant.id)} onChanged={onChanged} />
        <details className="tts-legacy-models">
          <summary>その他のモデル</summary>
          <CatalogCards items={sort(catalog.models.filter(isOtherModel))} registry={registry} busy={busy} onStart={(item) => void start(item)} onVariant={(modelId, variant) => void startVariant(modelId, variant.id)} onChanged={onChanged} />
        </details>
        {error && <p className="warning-text">{error}</p>}
        <DialogFooter className={job ? "download-dialog-footer" : ""}>
          {job && (
            <div className="tts-install-progress" role="status">
              <b>{job.state === "complete" ? "導入が完了しました" : job.state === "failed" ? "導入に失敗しました" : "必要な資産を導入中"}</b>
              <span>{job.currentFile ?? job.stage}</span>
              <div className="progress-bar determinate">
                <i style={{ width: `${progress}%` }} />
              </div>
              {job.error && <p>{job.error}</p>}
            </div>
          )}
          <span className="dialog-footer-actions">
            <button type="button" className="secondary" onClick={onClose}>
              閉じる
            </button>
            {job && ["queued", "running"].includes(job.state) && (
              <button type="button" className="danger" onClick={() => void cancel()}>
                取消
              </button>
            )}
          </span>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}

function TtsModelSelector({
  registry,
  catalog,
  isScratch,
  error,
  onRegistry,
  onError,
  onSelection,
  onAdd,
  onLibrary,
  onDetails,
}: {
  registry: TtsRegistry | null;
  catalog: TtsCatalog | null;
  isScratch: boolean;
  error: string;
  onRegistry: (value: TtsRegistry) => void;
  onError: (value: string) => void;
  onSelection: (value: TtsProjectSelection) => void;
  onAdd: () => void;
  onLibrary: () => void;
  onDetails: (id: string) => void;
}) {
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const models = sortTtsModelCards(registry?.models ?? []);
  const selectedId = registry ? (registry.activeModelId ?? registry.defaultModelId ?? null) : null;
  const selectedCard = models.find((card) => card.id === selectedId) ?? models[0];
  const choose = async (id: string) => {
    if (!registry || switchingId) return false;
    const card = models.find((item) => item.id === id);
    if (!card) return false;
    setSwitchingId(id);
    try {
      const result = await switchTtsModel(card, registry, isScratch);
      onRegistry(result.registry);
      if (result.selection) onSelection(result.selection);
      if (result.preparationError) {
        onError(`モデルは切り替わりましたが、${result.preparationError}`);
        return false;
      }
      onError("");
      return true;
    } catch (reason) {
      onError(`音声モデルを切り替えられませんでした: ${(reason as Error).message}`);
      return false;
    } finally {
      setSwitchingId(null);
    }
  };
  const selectedContent =
    selectedCard && registry ? (
      <TtsCardContent card={selectedCard} registry={registry} isDefault />
    ) : (
      <span className="model-selection-empty">
        <strong>{registry ? "音声モデルがありません" : "音声モデルを読み込んでいます…"}</strong>
        <span>展開してモデルを追加できます</span>
      </span>
    );
  const additions = [
    <button key="catalog" type="button" className="tts-add-card model-add-card registry-add-card" disabled={!catalog?.models.length} onClick={onAdd}>
      <strong>+ 音声モデル</strong>
      <span>Irodori-TTS標準モデル</span>
    </button>,
    <button key="library" type="button" className="tts-add-card model-add-card registry-add-card" onClick={onLibrary}>
      <strong>+ ストレージから追加</strong>
      <span>既存Irodori-TTSライブラリ</span>
    </button>,
  ];
  return (
    <>
      <ModelSelectionPopover
        label="音声モデル"
        selectedId={selectedId}
        selectedContent={selectedContent}
        options={models.map((card) => ({
          id: card.id,
          content: registry && <TtsCardContent card={card} registry={registry} isDefault={card.id === selectedId} compressMetadata />,
        }))}
        additions={additions}
        loading={!registry}
        error={error}
        onSelect={choose}
        onDetails={selectedCard ? () => onDetails(selectedCard.id) : undefined}
      />
      {switchingId && (
        <ModalBackdrop onClose={() => undefined} disabled>
          <TtsModelOperationNotice message="モデルを切り替えています…" />
        </ModalBackdrop>
      )}
    </>
  );
}

export function TtsRegistrySetting({ isScratch, onLegacyEngine: _onLegacyEngine, onSelectionChanged }: { isScratch: boolean; onLegacyEngine: (path: string) => void; onSelectionChanged: (value: TtsProjectSelection) => void }) {
  const [registry, setRegistry] = useState<TtsRegistry | null>(modelRegistryCache.tts());
  const [catalog, setCatalog] = useState<TtsCatalog | null>(modelRegistryCache.catalog());
  const [message, setMessage] = useState("");
  const [open, setOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [detailsId, setDetailsId] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState("");
  const acceptRegistry = useCallback((value: TtsRegistry) => {
    modelRegistryCache.setTts(value);
    setRegistry(value);
  }, []);
  const loadRegistry = useCallback(async () => {
    const [nextRegistry, nextCatalog] = await Promise.all([api.ttsRegistry(), api.ttsCatalog()]);
    acceptRegistry({ ...nextRegistry, libraries: nextRegistry.libraries ?? [] });
    modelRegistryCache.setCatalog(nextCatalog);
    setCatalog(nextCatalog);
    setMessage("");
  }, [acceptRegistry]);
  const refresh = useCallback(async () => {
    try {
      await loadRegistry();
    } catch (error) {
      setMessage((error as Error).message);
    }
  }, [loadRegistry]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const selectedId = registry ? (registry.activeModelId ?? registry.defaultModelId ?? null) : null;
  const detailsCard = registry?.models.find((card) => card.id === detailsId);
  return (
    <div className="tts-registry-setting">
      <div className="settings-panel-intro">
        <h2>Irodori-TTS設定</h2>
        <p className="subtle">モデルを選ぶと、対応するIrodori-TTSエンジンとCodecをSCENAが自動管理します。</p>
      </div>
      {registry?.missingProjectAssets?.includes("model") && <p className="warning-text">このプロジェクトの音声モデルがありません。同じrevisionを追加してください。</p>}
      <TtsModelSelector registry={registry} catalog={catalog} isScratch={isScratch} error={selectionError} onRegistry={acceptRegistry} onError={setSelectionError} onSelection={onSelectionChanged} onAdd={() => setOpen(true)} onLibrary={() => setLibraryOpen(true)} onDetails={setDetailsId} />
      {message && <p role="status">{message}</p>}
      {open && catalog && <AddModelDialog catalog={catalog} registry={registry} onClose={() => setOpen(false)} onInstalled={loadRegistry} onChanged={refresh} />}
      {libraryOpen && <AddLibraryDialog onClose={() => setLibraryOpen(false)} onChanged={loadRegistry} />}
      {detailsCard && registry && <TtsModelDialog card={detailsCard} registry={registry} isDefault={detailsCard.id === selectedId} isScratch={isScratch} onClose={() => setDetailsId(null)} onChanged={acceptRegistry} onSelectionChanged={onSelectionChanged} />}
    </div>
  );
}
