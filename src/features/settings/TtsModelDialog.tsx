import { useState } from "react";
import { api, openExternal } from "../../api";
import type { TtsAssetCard, TtsCatalogItem, TtsInstalledVariant, TtsProjectSelection, TtsRegistry } from "../../types";
import { formatGb } from "../shared/formatBytes";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { TtsModelOperationNotice } from "./TtsModelOperationNotice";

// eslint-disable-next-line react-refresh/only-export-components -- shared text formatter for the paired registry view.
export const formatSize = (bytes?: number | null) => (bytes == null ? "容量未取得" : formatGb(bytes));
const MODEL_PREPARATION_POLL_MS = 500;
const MODEL_PREPARATION_WAIT_MS = 5 * 60 * 1000;

async function waitForModelPreparation(modelId: string): Promise<string | null> {
  const deadline = Date.now() + MODEL_PREPARATION_WAIT_MS;
  while (Date.now() < deadline) {
    const status = await api.ttsRuntimeStatus();
    if (status.modelId !== modelId) return "選択したモデルの準備状況を確認できませんでした。";
    if (status.state === "failed") return status.error ?? "音声モデルの準備に失敗しました。";
    if (status.state !== "preparing") return null;
    await new Promise<void>((resolve) => globalThis.setTimeout(resolve, MODEL_PREPARATION_POLL_MS));
  }
  return "音声モデルの準備が続いています。しばらくしてからお試しください。";
}
export function CapabilityList({ item }: { item: TtsCatalogItem | TtsAssetCard }) {
  const capabilities = [
    { label: "音声生成", supported: true },
    { label: "VoiceDesign", supported: !!item.voiceDesign },
  ];
  return (
    <ul className="tts-capabilities">
      {capabilities.map(({ label, supported }) => (
        <li key={label} className={supported ? "is-supported" : "is-unsupported"} aria-label={`${label}：${supported ? "対応" : "非対応"}`}>
          {label}
        </li>
      ))}
    </ul>
  );
}

// eslint-disable-next-line react-refresh/only-export-components -- shared model-selection action for the paired registry view.
export async function switchTtsModel(card: TtsAssetCard, registry: TtsRegistry, isScratch: boolean) {
  void registry;
  void isScratch;
  const nextRegistry = await api.setTtsDefaults(card.id);
  let preparationError: string | null;
  try {
    preparationError = await waitForModelPreparation(card.id);
  } catch (error) {
    preparationError = `準備状況を確認できませんでした: ${(error as Error).message}`;
  }
  return { registry: nextRegistry, selection: undefined, preparationError };
}

function modelSelectionLabel(isDefault: boolean, isScratch: boolean) {
  void isScratch;
  return isDefault ? "選択中のモデル" : "このモデルを選択";
}

function ModelInformation({ card, libraryName, variant }: { card: TtsAssetCard; libraryName?: string; variant?: TtsInstalledVariant }) {
  return (
    <section>
      <h3>モデル情報</h3>
      <dl className="tts-model-facts">
        <dt>世代</dt>
        <dd>{card.generation}</dd>
        <dt>revision</dt>
        <dd>{variant?.revision ?? card.revision}</dd>
        {card.author && (
          <>
            <dt>作者</dt>
            <dd>{card.author}</dd>
          </>
        )}
        {card.releasedAt && (
          <>
            <dt>リリース日</dt>
            <dd>{card.releasedAt}</dd>
          </>
        )}
        {card.publisher && (
          <>
            <dt>配布者</dt>
            <dd>{card.publisher}</dd>
          </>
        )}
        {card.license && (
          <>
            <dt>ライセンス</dt>
            <dd>{card.license}</dd>
          </>
        )}
        {libraryName && (
          <>
            <dt>接続先</dt>
            <dd>{libraryName}</dd>
          </>
        )}
        <dt>使用容量</dt>
        <dd>{formatSize(variant?.diskBytes ?? card.diskBytes)}</dd>
        {card.legacy && (
          <>
            <dt>区分</dt>
            <dd>レガシー</dd>
          </>
        )}
      </dl>
    </section>
  );
}

function VariantChoices({ card, value, busy, onChange, onDelete }: { card: TtsAssetCard; value: string; busy: boolean; onChange: (value: string) => void; onDelete: (value: string) => Promise<void> }) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const variants = card.installedVariants ?? [];
  if (!variants.length) return null;
  return (
    <div className="tts-variant-setting">
      <h3>使用するバリアント</h3>
      <div className="tts-variant-radio" role="radiogroup">
        {variants.map((variant) => {
          const confirming = confirmDeleteId === variant.id;
          return (
            <span className={`tts-variant-choice${confirming ? " is-confirming" : ""}`} key={variant.id} onMouseLeave={() => !busy && setConfirmDeleteId(null)}>
              <button
                type="button"
                className="tts-variant-select"
                role="radio"
                aria-checked={value === variant.id}
                disabled={busy}
                onClick={() => {
                  setConfirmDeleteId(null);
                  onChange(variant.id);
                }}
              >
                {variant.precision}
              </button>
              <button
                type="button"
                className="tts-variant-delete"
                disabled={busy}
                title={confirming ? `${variant.precision}を削除する` : `${variant.precision}を削除`}
                aria-label={confirming ? `${variant.precision}バリアントの削除を確定` : `${variant.precision}バリアントを削除`}
                onClick={(event) => {
                  event.stopPropagation();
                  if (confirming) {
                    setConfirmDeleteId(null);
                    void onDelete(variant.id);
                  } else setConfirmDeleteId(variant.id);
                }}
              >
                {confirming ? "✓" : "×"}
              </button>
            </span>
          );
        })}
      </div>
    </div>
  );
}

function ModelDialogLeading({ card, confirming, busy, onRemove }: { card: TtsAssetCard; confirming: boolean; busy: boolean; onRemove: () => void }) {
  const managed = card.source === "managed";
  const removeLabel = confirming ? (managed ? "もう一度押してモデルを削除" : "もう一度押して登録解除") : managed ? "モデルを削除" : "登録解除";
  return (
    <span className="tts-dialog-leading-actions">
      {card.modelCardUrl && (
        <button type="button" className="secondary" disabled={busy} onClick={() => void openExternal(card.modelCardUrl!)}>
          モデルカード
        </button>
      )}
      <button type="button" className={`danger${confirming ? " is-confirming" : ""}`} disabled={busy} onClick={onRemove}>
        {removeLabel}
      </button>
    </span>
  );
}

function ModelDialogContent({ card, libraryName, variantId, variantBusy, onVariant, onDeleteVariant }: { card: TtsAssetCard; libraryName?: string; variantId: string; variantBusy: boolean; onVariant: (value: string) => void; onDeleteVariant: (value: string) => Promise<void> }) {
  const variant = card.installedVariants?.find((item) => item.id === variantId);
  return (
    <div className="tts-model-dialog-content">
      {card.description && <p className="tts-model-description">{card.description}</p>}
      <section>
        <h3>対応機能</h3>
        <CapabilityList item={card} />
        <VariantChoices card={card} value={variantId} busy={variantBusy} onChange={onVariant} onDelete={onDeleteVariant} />
      </section>
      <ModelInformation card={card} libraryName={libraryName} variant={variant} />
    </div>
  );
}

function modelOperationMessage(removing: boolean, selecting: boolean, managed: boolean) {
  if (removing) return managed ? "モデルを削除しています…" : "モデルの登録を解除しています…";
  return selecting ? "モデルを切り替えています…" : null;
}

export function TtsModelDialog({
  card,
  registry,
  isDefault,
  isScratch,
  onClose,
  onChanged,
  onSelectionChanged,
}: {
  card: TtsAssetCard;
  registry: TtsRegistry;
  isDefault: boolean;
  isScratch: boolean;
  onClose: () => void;
  onChanged: (value: TtsRegistry) => void;
  onSelectionChanged: (value: TtsProjectSelection) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState("");
  const [variantId, setVariantId] = useState(card.activeVariantId ?? card.installedVariants?.[0]?.id ?? "pytorch-fp32");
  const [variantBusy, setVariantBusy] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const busy = removing || selecting;
  const remove = async () => {
    if (removing) return;
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setRemoving(true);
    setMessage("");
    try {
      onChanged(await api.deleteTtsAsset("model", card.id));
      onClose();
    } catch (error) {
      setMessage((error as Error).message);
      setConfirming(false);
    } finally {
      setRemoving(false);
    }
  };
  const select = async () => {
    setSelecting(true);
    setMessage("");
    try {
      const result = await switchTtsModel(card, registry, isScratch);
      onChanged(result.registry);
      if (result.selection) onSelectionChanged(result.selection);
      setMessage(result.preparationError ? `モデルは切り替わりましたが、${result.preparationError}` : "");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setSelecting(false);
    }
  };
  const changeVariant = async (nextVariantId: string) => {
    if (nextVariantId === variantId || variantBusy) return;
    const previousVariantId = variantId;
    setVariantId(nextVariantId);
    setVariantBusy(true);
    try {
      onChanged(await api.setTtsActiveVariant(card.id, nextVariantId));
      setMessage("");
    } catch (error) {
      setVariantId(previousVariantId);
      setMessage((error as Error).message);
    } finally {
      setVariantBusy(false);
    }
  };
  const deleteVariant = async (deleteVariantId: string) => {
    if (variantBusy) return;
    setVariantBusy(true);
    try {
      const nextRegistry = await api.deleteTtsVariant(card.id, deleteVariantId);
      const nextCard = nextRegistry.models.find((item) => item.id === card.id);
      onChanged(nextRegistry);
      if (!nextCard) return onClose();
      setVariantId(nextCard.activeVariantId ?? nextCard.installedVariants?.[0]?.id ?? "");
      setMessage("");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setVariantBusy(false);
    }
  };
  const defaultButton = (
    <button type="button" className={`secondary tts-default-button${isDefault ? " is-active" : ""}`} disabled={isDefault || busy} onClick={() => void select()}>
      {modelSelectionLabel(isDefault, isScratch)}
    </button>
  );
  const library = registry.libraries.find((item) => item.id === card.libraryId);
  const unregister = card.source !== "managed";
  const leading = <ModelDialogLeading card={card} confirming={confirming} busy={busy} onRemove={() => void remove()} />;
  return (
    <ModalBackdrop onClose={onClose} disabled={busy} fileDropPolicy="dismiss">
      <section className="modal tts-model-dialog" role="dialog" aria-modal="true">
        <DialogHeader title={card.displayName} description={card.repo ?? undefined} actions={defaultButton} />
        <ModelDialogContent card={card} libraryName={library?.displayName} variantId={variantId} variantBusy={variantBusy || busy} onVariant={(value) => void changeVariant(value)} onDeleteVariant={deleteVariant} />
        {library && !library.available && <p className="warning-text">接続先が見つかりません。再接続するとこの登録をそのまま利用できます。</p>}
        {unregister && <p className="subtle">登録解除しても元のモデルファイルは削除されません。</p>}
        {message && <p className="warning-text">{message}</p>}
        <DialogFooter leading={leading}>
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            閉じる
          </button>
        </DialogFooter>
      </section>
      <TtsModelOperationNotice message={modelOperationMessage(removing, selecting, !unregister)} />
    </ModalBackdrop>
  );
}
